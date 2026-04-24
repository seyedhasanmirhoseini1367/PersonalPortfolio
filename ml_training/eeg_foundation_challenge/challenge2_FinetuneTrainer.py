# challenge2_finetune.py
# Complete fine-tuning pipeline for p-factor prediction

import torch
import torch.nn as nn
import numpy as np
import os
import time
from datetime import datetime
import json
from torch.utils.data import DataLoader, Subset
import matplotlib.pyplot as plt
from tqdm import tqdm
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
import warnings

warnings.filterwarnings('ignore')

from EEG_Competition.dataloader_challenge2 import PFactorFineTuneDataset, pfactor_raw_collate_fn
from EEG_Competition.Pretrain_Model import EEGFoundationModel


class PFactorFinetuneTrainer:
    """
    Trainer for p-factor prediction using pre-trained transformer
    """

    def __init__(self, model, train_loader, val_loader, optimizer, device, config, freeze_encoder=True):
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.optimizer = optimizer
        self.device = device
        self.config = config
        self.freeze_encoder = freeze_encoder

        # Add p-factor task head
        if 'p_factor' not in self.model.task_heads:
            self.model.add_task_head('p_factor', 'regression', output_dim=1)

        # Freeze encoder if specified
        if freeze_encoder:
            self._freeze_encoder()

        # Loss function
        self.criterion = nn.MSELoss()

        # Training history
        self.train_losses = []
        self.val_losses = []
        self.train_maes = []
        self.val_maes = []
        self.train_r2s = []
        self.val_r2s = []
        self.train_nrmses = []
        self.val_nrmses = []
        self.learning_rates = []

        # Best model tracking
        self.best_val_nrmse = float('inf')
        self.best_val_loss = float('inf')
        self.patience_counter = 0

        # Create experiment directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        freeze_str = 'frozen' if freeze_encoder else 'unfrozen'
        self.experiment_dir = f"homedir/analysis/derivatives/challenge2_pfactor_{freeze_str}_{timestamp}"
        os.makedirs(self.experiment_dir, exist_ok=True)

    def _freeze_encoder(self):
        """Freeze all parameters except task head"""
        print("Freezing encoder weights - only training p-factor head")
        for name, param in self.model.named_parameters():
            if 'task_heads' not in name:
                param.requires_grad = False

        trainable = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in self.model.parameters())
        print(f"Trainable parameters: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    def save_config(self):
        config_path = os.path.join(self.experiment_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def save_checkpoint(self, epoch, is_best=False):
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'train_losses': self.train_losses,
            'val_losses': self.val_losses,
            'train_nrmses': self.train_nrmses,
            'val_nrmses': self.val_nrmses,
            'best_val_nrmse': self.best_val_nrmse,
            'config': self.config
        }

        checkpoint_path = os.path.join(self.experiment_dir, f"checkpoint_epoch_{epoch:04d}.pt")
        torch.save(checkpoint, checkpoint_path)

        if is_best:
            best_path = os.path.join(self.experiment_dir, "best_model.pt")
            torch.save(checkpoint, best_path)
            print(f"  Best model saved - Val NRMSE: {self.best_val_nrmse:.4f}")

    def train_epoch(self):
        """Train one epoch"""
        self.model.train()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        num_batches = 0

        train_bar = tqdm(self.train_loader, desc='Training')
        for batch in train_bar:
            eeg = batch['eeg'].to(self.device)  # (batch, 129, 200)
            p_factor = batch['p_factor'].to(self.device)  # (batch,)

            self.optimizer.zero_grad()

            # Forward pass
            output = self.model(eeg, mode='finetune', task_name='p_factor')
            prediction = output['prediction'].squeeze(-1)

            # Calculate loss
            loss = self.criterion(prediction, p_factor)

            # Backward pass
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            # Statistics
            total_loss += loss.item()
            all_predictions.extend(prediction.detach().cpu().numpy())
            all_targets.extend(p_factor.cpu().numpy())
            num_batches += 1

            train_bar.set_postfix({
                'Loss': f"{loss.item():.4f}",
                'Pred': f"{prediction.mean().item():.3f}",
                'Target': f"{p_factor.mean().item():.3f}"
            })

        # Calculate metrics
        epoch_loss = total_loss / num_batches
        epoch_mae = mean_absolute_error(all_targets, all_predictions)
        epoch_r2 = r2_score(all_targets, all_predictions)
        epoch_rmse = mean_squared_error(all_targets, all_predictions, squared=False)
        epoch_nrmse = epoch_rmse / (np.std(all_targets) + 1e-8)

        return epoch_loss, epoch_mae, epoch_r2, epoch_nrmse

    def validate(self):
        """Validation phase"""
        self.model.eval()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        num_batches = 0

        with torch.no_grad():
            val_bar = tqdm(self.val_loader, desc='Validation')
            for batch in val_bar:
                eeg = batch['eeg'].to(self.device)
                p_factor = batch['p_factor'].to(self.device)

                output = self.model(eeg, mode='finetune', task_name='p_factor')
                prediction = output['prediction'].squeeze(-1)

                loss = self.criterion(prediction, p_factor)

                total_loss += loss.item()
                all_predictions.extend(prediction.cpu().numpy())
                all_targets.extend(p_factor.cpu().numpy())
                num_batches += 1

                val_bar.set_postfix({'Val_Loss': f"{loss.item():.4f}"})

        val_loss = total_loss / num_batches
        val_mae = mean_absolute_error(all_targets, all_predictions)
        val_r2 = r2_score(all_targets, all_predictions)
        val_rmse = mean_squared_error(all_targets, all_predictions, squared=False)
        val_nrmse = val_rmse / (np.std(all_targets) + 1e-8)

        return val_loss, val_mae, val_r2, val_nrmse, all_predictions, all_targets

    def train(self, epochs):
        """Main training loop"""
        print(f"\nStarting Challenge 2: P-Factor Prediction")
        print(f"Experiment directory: {self.experiment_dir}")
        print(f"Training samples: {len(self.train_loader.dataset)}")
        print(f"Validation samples: {len(self.val_loader.dataset)}")
        print(f"Freeze encoder: {self.freeze_encoder}")
        print("-" * 80)

        self.save_config()

        # Learning rate scheduler
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode='min',
            factor=0.5,
            patience=10,
            verbose=True,
            min_lr=1e-6
        )

        for epoch in range(epochs):
            start_time = time.time()

            print(f"\nEpoch {epoch + 1}/{epochs}")
            print("-" * 50)

            # Training
            train_loss, train_mae, train_r2, train_nrmse = self.train_epoch()
            self.train_losses.append(train_loss)
            self.train_maes.append(train_mae)
            self.train_r2s.append(train_r2)
            self.train_nrmses.append(train_nrmse)

            # Validation
            val_loss, val_mae, val_r2, val_nrmse, val_preds, val_targets = self.validate()
            self.val_losses.append(val_loss)
            self.val_maes.append(val_mae)
            self.val_r2s.append(val_r2)
            self.val_nrmses.append(val_nrmse)

            # Update learning rate
            scheduler.step(val_nrmse)
            current_lr = self.optimizer.param_groups[0]['lr']
            self.learning_rates.append(current_lr)

            epoch_time = time.time() - start_time

            # Epoch summary
            print(f"\nEpoch {epoch + 1} Summary:")
            print(f"   Train: Loss={train_loss:.6f}, NRMSE={train_nrmse:.4f}, MAE={train_mae:.4f}, R²={train_r2:.4f}")
            print(f"   Val:   Loss={val_loss:.6f}, NRMSE={val_nrmse:.4f}, MAE={val_mae:.4f}, R²={val_r2:.4f}")
            print(f"   LR: {current_lr:.2e}, Time: {epoch_time:.2f}s")

            # Model selection
            if val_nrmse < self.best_val_nrmse:
                self.best_val_nrmse = val_nrmse
                self.best_val_loss = val_loss
                self.save_checkpoint(epoch + 1, is_best=True)
                self.patience_counter = 0
            else:
                self.patience_counter += 1

            # Periodic checkpoint
            if (epoch + 1) % 10 == 0:
                self.save_checkpoint(epoch + 1)

            # Early stopping
            if self.patience_counter >= self.config.get('patience', 20):
                print(f"\nEarly stopping triggered after {epoch + 1} epochs")
                break

        # Final save
        self.save_checkpoint(epochs)
        self._plot_training_curves()
        self._plot_prediction_scatter(val_preds, val_targets)

        return {
            'best_val_nrmse': self.best_val_nrmse,
            'best_val_loss': self.best_val_loss,
            'final_train_nrmse': self.train_nrmses[-1],
            'final_val_nrmse': self.val_nrmses[-1],
            'experiment_dir': self.experiment_dir,
            'total_epochs': len(self.train_losses)
        }

    def _plot_training_curves(self):
        """Plot training curves"""
        fig, axes = plt.subplots(1, 4, figsize=(20, 5))

        axes[0].plot(self.train_losses, label='Train', marker='o')
        axes[0].plot(self.val_losses, label='Val', marker='s')
        axes[0].set_title('MSE Loss')
        axes[0].legend()
        axes[0].grid(True)

        axes[1].plot(self.train_nrmses, label='Train', marker='o', color='red')
        axes[1].plot(self.val_nrmses, label='Val', marker='s', color='darkred')
        axes[1].set_title('Normalized RMSE (Challenge Metric)')
        axes[1].legend()
        axes[1].grid(True)

        axes[2].plot(self.train_maes, label='Train', marker='o')
        axes[2].plot(self.val_maes, label='Val', marker='s')
        axes[2].set_title('Mean Absolute Error')
        axes[2].legend()
        axes[2].grid(True)

        axes[3].plot(self.train_r2s, label='Train', marker='o')
        axes[3].plot(self.val_r2s, label='Val', marker='s')
        axes[3].set_title('R² Score')
        axes[3].legend()
        axes[3].grid(True)

        plt.tight_layout()
        plot_path = os.path.join(self.experiment_dir, "training_curves.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_prediction_scatter(self, predictions, targets):
        """Plot prediction vs target scatter"""
        plt.figure(figsize=(8, 8))
        plt.scatter(targets, predictions, alpha=0.5)

        min_val = min(min(targets), min(predictions))
        max_val = max(max(targets), max(predictions))
        plt.plot([min_val, max_val], [min_val, max_val], 'r--', label='Perfect Prediction')

        plt.xlabel('Actual P-Factor')
        plt.ylabel('Predicted P-Factor')
        plt.title('P-Factor Prediction: Actual vs Predicted')
        plt.legend()
        plt.grid(True, alpha=0.3)

        plot_path = os.path.join(self.experiment_dir, "prediction_scatter.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()


def split_dataset_by_subject(dataset, train_ratio=0.8, seed=42):
    """
    Split dataset by subject to prevent data leakage
    """
    np.random.seed(seed)

    # Get unique subjects
    all_subjects = list(set([item[2] for item in dataset.windows]))
    np.random.shuffle(all_subjects)

    # Split subjects
    split_idx = int(len(all_subjects) * train_ratio)
    train_subjects = set(all_subjects[:split_idx])
    val_subjects = set(all_subjects[split_idx:])

    # Get indices for each split
    train_indices = [i for i, item in enumerate(dataset.windows) if item[2] in train_subjects]
    val_indices = [i for i, item in enumerate(dataset.windows) if item[2] in val_subjects]

    # Create subsets
    train_dataset = Subset(dataset, train_indices)
    val_dataset = Subset(dataset, val_indices)

    print(f"Train subjects: {len(train_subjects)}, Val subjects: {len(val_subjects)}")
    print(f"Train windows: {len(train_indices)}, Val windows: {len(val_indices)}")

    return train_dataset, val_dataset


# ===================== Main Execution =====================

if __name__ == '__main__':
    # Configuration
    config = {
        'batch_size': 64,
        'learning_rate': 1e-4,  # Higher for frozen; use 1e-5 for unfrozen
        'epochs': 50,
        'weight_decay': 1e-4,
        'patience': 20,
        'freeze_encoder': True,  # Set False for full fine-tuning
        'n_windows_per_subject': 20,  # More windows = more data
        'device': 'cuda' if torch.cuda.is_available() else 'cpu'
    }

    print(f"Using device: {config['device']}")

    # ============ Load Pre-trained Model ============
    pretrain_checkpoint = ""homedir/analysis/derivatives/pretraining_vicreg_20251005_114620/best_model.pt"  # UPDATE THIS!

    print(f"\nLoading pre-trained model from: {pretrain_checkpoint}")
    checkpoint = torch.load(pretrain_checkpoint, map_location=config['device'])

    # Create model with SAME architecture as pre-training
    model = EEGFoundationModel(
        n_channels=129,
        patch_size=25,
        d_model=32,
        n_heads=4,
        n_encoder_layers=2,
        n_decoder_layers=2,
        dim_feedforward=16,
        dropout=0.1
    ).to(config['device'])

    # Load pre-trained weights
    model.load_state_dict(checkpoint['model_state_dict'], strict=False)
    print("Pre-trained weights loaded successfully!")

    # ============ Create Dataset ============
    base_path = 'D:/EEGChallenge'
    root_dirs = [os.path.join(base_path, d) for d in os.listdir(base_path)
                 if os.path.isdir(os.path.join(base_path, d)) and d.startswith('R')]

    print(f"\nFound {len(root_dirs)} directories")

    # Create full dataset
    full_dataset = PFactorFineTuneDataset(
        root_dirs=root_dirs,
        window_length_s=2.0,
        sfreq=100,
        n_windows_per_subject=config['n_windows_per_subject'],
        tasks=None  # Use all tasks
    )

    # Split by subject
    train_dataset, val_dataset = split_dataset_by_subject(full_dataset, train_ratio=0.8)

    # Create DataLoaders
    train_loader = DataLoader(
        train_dataset,
        batch_size=config['batch_size'],
        shuffle=True,
        collate_fn=pfactor_raw_collate_fn,
        num_workers=0,
        pin_memory=False
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=config['batch_size'],
        shuffle=False,
        collate_fn=pfactor_raw_collate_fn,
        num_workers=0,
        pin_memory=False
    )

    # ============ Setup Optimizer ============
    if config['freeze_encoder']:
        # Only optimize task head
        params_to_optimize = [p for p in model.parameters() if p.requires_grad]
    else:
        params_to_optimize = model.parameters()

    optimizer = torch.optim.AdamW(
        params_to_optimize,
        lr=config['learning_rate'],
        weight_decay=config['weight_decay']
    )

    # ============ Create Trainer and Start Fine-tuning ============
    trainer = PFactorFinetuneTrainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        optimizer=optimizer,
        device=config['device'],
        config=config,
        freeze_encoder=config['freeze_encoder']
    )

    # Start training
    results = trainer.train(config['epochs'])

    print(f"\nFine-tuning completed!")
    print(f"Best validation NRMSE (Challenge Metric): {results['best_val_nrmse']:.4f}")
    print(f"Best validation loss: {results['best_val_loss']:.6f}")
    print(f"Results saved in: {results['experiment_dir']}")

    # Save weights in submission format
    submission_weights = {
        'model_state_dict': model.state_dict()
    }
    torch.save(submission_weights, 'weights_challenge_2.pt')
    print(f"\nSubmission weights saved: weights_challenge_2.pt")
