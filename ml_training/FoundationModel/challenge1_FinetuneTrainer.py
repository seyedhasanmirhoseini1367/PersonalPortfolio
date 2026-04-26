# challenge1_FinetuneTrainer.py
import torch
import torch.nn as nn
import numpy as np
import os
import time
from datetime import datetime
import json
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
from tqdm import tqdm
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
import warnings

warnings.filterwarnings('ignore')


class EEGFinetuneTrainer:
    """
    Fine-tuning trainer for reaction time prediction task
    Loads pre-trained model and fine-tunes task-specific head
    """

    def __init__(self, model, train_loader, val_loader, optimizer, device, config, freeze_encoder=True):
        """
        Args:
            model: Pre-trained EEGFoundationModel
            train_loader: DataLoader with windowed EEG data
            val_loader: Validation DataLoader
            optimizer: Optimizer for fine-tuning
            device: 'cuda' or 'cpu'
            config: Fine-tuning configuration dict
            freeze_encoder: If True, only train task head; if False, train entire model
        """
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.optimizer = optimizer
        self.device = device
        self.config = config
        self.freeze_encoder = freeze_encoder

        if 'rt_prediction' not in self.model.task_heads:
            self.model.add_task_head('rt_prediction', 'regression', output_dim=1)

        # Freeze encoder if specified
        if freeze_encoder:
            self._freeze_encoder()

        # Loss function — RT regression only
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
        self.best_val_loss = float('inf')
        self.best_val_nrmse = float('inf')
        self.best_model_state = None
        self.patience_counter = 0

        # Create experiment directory
        self.experiment_dir = self._create_experiment_dir()

    def _freeze_encoder(self):
        """Freeze all parameters except task head"""
        print("Freezing encoder weights - only training task head")
        for name, param in self.model.named_parameters():
            if 'task_heads' not in name:
                param.requires_grad = False

        # Print trainable parameters
        trainable = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in self.model.parameters())
        print(f"Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    def _create_experiment_dir(self):
        """Create unique experiment directory"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exp_dir = f"D:/eegchallenge_results/finetuning_{timestamp}"
        os.makedirs(exp_dir, exist_ok=True)
        return exp_dir

    def save_config(self):
        """Save configuration to JSON"""
        config_path = os.path.join(self.experiment_dir, "finetune_config.json")
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def save_checkpoint(self, epoch, is_best=False):
        """Save model checkpoint"""
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'train_losses': self.train_losses,
            'val_losses': self.val_losses,
            'train_maes': self.train_maes,
            'val_maes': self.val_maes,
            'train_r2s': self.train_r2s,
            'val_r2s': self.val_r2s,
            'train_nrmses': self.train_nrmses,
            'val_nrmses': self.val_nrmses,
            'best_val_loss': self.best_val_loss,
            'best_val_nrmse': self.best_val_nrmse,
            'config': self.config
        }

        checkpoint_path = os.path.join(self.experiment_dir, f"checkpoint_epoch_{epoch:04d}.pt")
        torch.save(checkpoint, checkpoint_path)

        if is_best:
            best_path = os.path.join(self.experiment_dir, "best_model.pt")
            torch.save(checkpoint, best_path)
            print(f"  Best model saved - Val NRMSE: {self.best_val_nrmse:.4f}, Val Loss: {self.best_val_loss:.6f}")

    def train_epoch(self):
        """Train one epoch — RT regression."""
        self.model.train()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        num_batches = 0

        train_bar = tqdm(self.train_loader, desc='Training')
        for batch in train_bar:
            eeg       = batch['eeg'].to(self.device)
            rt_target = batch['rt'].to(self.device)

            self.optimizer.zero_grad()

            output     = self.model(eeg, mode='finetune', task_name='rt_prediction')
            prediction = output['prediction'].squeeze(-1)

            loss = self.criterion(prediction, rt_target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            total_loss += loss.item()
            all_predictions.extend(prediction.detach().cpu().numpy())
            all_targets.extend(rt_target.cpu().numpy())
            num_batches += 1

            train_bar.set_postfix({
                'Loss':   f"{loss.item():.4f}",
                'Pred':   f"{prediction.mean().item():.3f}s",
                'Target': f"{rt_target.mean().item():.3f}s",
            })

        epoch_loss  = total_loss / num_batches
        epoch_mae   = mean_absolute_error(all_targets, all_predictions)
        epoch_r2    = r2_score(all_targets, all_predictions)
        epoch_rmse  = root_mean_squared_error(all_targets, all_predictions)
        epoch_nrmse = epoch_rmse / (np.std(all_targets) + 1e-8)

        return epoch_loss, epoch_mae, epoch_r2, epoch_nrmse

    def validate(self):
        """Validation phase — RT regression."""
        self.model.eval()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        num_batches = 0

        with torch.no_grad():
            val_bar = tqdm(self.val_loader, desc='Validation')
            for batch in val_bar:
                eeg       = batch['eeg'].to(self.device)
                rt_target = batch['rt'].to(self.device)

                output     = self.model(eeg, mode='finetune', task_name='rt_prediction')
                prediction = output['prediction'].squeeze(-1)

                loss = self.criterion(prediction, rt_target)

                total_loss += loss.item()
                all_predictions.extend(prediction.cpu().numpy())
                all_targets.extend(rt_target.cpu().numpy())
                num_batches += 1

                val_bar.set_postfix({
                    'Val_Loss': f"{loss.item():.4f}",
                    'Pred':     f"{prediction.mean().item():.3f}s",
                })

        val_loss  = total_loss / num_batches
        val_mae   = mean_absolute_error(all_targets, all_predictions)
        val_r2    = r2_score(all_targets, all_predictions)
        val_rmse  = root_mean_squared_error(all_targets, all_predictions)
        val_nrmse = val_rmse / (np.std(all_targets) + 1e-8)

        return val_loss, val_mae, val_r2, val_nrmse, all_predictions, all_targets

    def train(self, epochs):
        """Main training loop"""
        print(f"\nStarting EEG Model Fine-tuning for Reaction Time Prediction")
        print(f"Experiment directory: {self.experiment_dir}")
        print(f"Training samples: {len(self.train_loader.dataset)}")
        print(f"Validation samples: {len(self.val_loader.dataset)}")
        print(f"Freeze encoder: {self.freeze_encoder}")
        print(f"Configuration: {json.dumps(self.config, indent=2)}")
        print("-" * 80)

        self.save_config()

        # Learning rate scheduler
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode='min',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
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
            scheduler.step(val_loss)
            current_lr = self.optimizer.param_groups[0]['lr']
            self.learning_rates.append(current_lr)

            epoch_time = time.time() - start_time

            # Epoch summary
            print(f"\nEpoch {epoch + 1} Summary:")
            print(f"   Train Loss: {train_loss:.6f} | MAE: {train_mae:.4f}s | R²: {train_r2:.4f} | NRMSE: {train_nrmse:.4f}")
            print(f"   Val Loss:   {val_loss:.6f} | MAE: {val_mae:.4f}s | R²: {val_r2:.4f} | NRMSE: {val_nrmse:.4f}")
            print(f"   Learning Rate: {current_lr:.2e}")
            print(f"   Time: {epoch_time:.2f}s")

            # Model selection based on NRMSE (challenge metric)
            if val_nrmse < self.best_val_nrmse:
                self.best_val_nrmse = val_nrmse
                self.best_val_loss = val_loss
                self.best_model_state = self.model.state_dict().copy()
                self.save_checkpoint(epoch + 1, is_best=True)
                self.patience_counter = 0
            else:
                self.patience_counter += 1

            # Periodic checkpoint
            if (epoch + 1) % self.config.get('checkpoint_interval', 10) == 0:
                self.save_checkpoint(epoch + 1)
            if (epoch + 1) % 5 == 0:
                self.save_checkpoint(epoch + 1)

            # Early stopping
            if self.patience_counter >= self.config.get('patience', 20):
                print(f"\nEarly stopping triggered after {epoch + 1} epochs")
                break

        # Final save
        self.save_checkpoint(len(self.train_losses))
        self._plot_training_curves()
        self._plot_prediction_scatter(val_preds, val_targets)

        return self._get_training_summary()

    def _plot_training_curves(self):
        """Plot training curves."""
        fig, axes = plt.subplots(1, 4, figsize=(20, 5))

        axes[0].plot(self.train_losses, label='Train Loss', marker='o')
        axes[0].plot(self.val_losses,   label='Val Loss',   marker='s')
        axes[0].set_title('MSE Loss')
        axes[0].set_xlabel('Epoch')
        axes[0].set_ylabel('Loss')
        axes[0].legend()
        axes[0].grid(True)

        axes[1].plot(self.train_nrmses, label='Train NRMSE', marker='o', color='red')
        axes[1].plot(self.val_nrmses,   label='Val NRMSE',   marker='s', color='darkred')
        axes[1].set_title('Normalized RMSE (Challenge Metric)')
        axes[1].set_xlabel('Epoch')
        axes[1].set_ylabel('NRMSE')
        axes[1].legend()
        axes[1].grid(True)

        axes[2].plot(self.train_maes, label='Train MAE', marker='o')
        axes[2].plot(self.val_maes,   label='Val MAE',   marker='s')
        axes[2].set_title('Mean Absolute Error')
        axes[2].set_xlabel('Epoch')
        axes[2].set_ylabel('MAE (seconds)')
        axes[2].legend()
        axes[2].grid(True)

        axes[3].plot(self.train_r2s, label='Train R²', marker='o')
        axes[3].plot(self.val_r2s,   label='Val R²',   marker='s')
        axes[3].set_title('R² Score')
        axes[3].set_xlabel('Epoch')
        axes[3].set_ylabel('R²')
        axes[3].legend()
        axes[3].grid(True)

        plt.tight_layout()
        plot_path = os.path.join(self.experiment_dir, "training_curves.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_prediction_scatter(self, predictions, targets):
        """Plot actual and predicted distributions side by side"""
        plt.figure(figsize=(10, 6))

        # Create scatter plot with different colors
        indices = range(len(targets))

        plt.scatter(indices, targets, color='blue', alpha=0.6, s=30, label='Actual RT')
        plt.scatter(indices, predictions, color='red', alpha=0.6, s=30, label='Predicted RT')

        plt.xlabel('Sample Index')
        plt.ylabel('Reaction Time (s)')
        plt.title('Reaction Time Prediction: Actual (Blue) vs Predicted (Red)')
        plt.legend()
        plt.grid(True, alpha=0.3)

        plot_path = os.path.join(self.experiment_dir, "prediction_comparison.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()

    # def _plot_prediction_scatter(self, predictions, targets):
    #     """Plot prediction vs target scatter"""
    #     plt.figure(figsize=(8, 8))
    #     plt.scatter(targets, predictions, alpha=0.5)
    #
    #     # Perfect prediction line
    #     min_val = min(min(targets), min(predictions))
    #     max_val = max(max(targets), max(predictions))
    #     plt.plot([min_val, max_val], [min_val, max_val], 'r--', label='Perfect Prediction')
    #
    #     plt.xlabel('Actual Reaction Time (s)')
    #     plt.ylabel('Predicted Reaction Time (s)')
    #     plt.title('Reaction Time Prediction: Actual vs Predicted')
    #     plt.legend()
    #     plt.grid(True, alpha=0.3)
    #
    #     plot_path = os.path.join(self.experiment_dir, "prediction_scatter.png")
    #     plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    #     plt.close()

    def _get_training_summary(self):
        """Get training summary."""
        return {
            'best_val_loss':     self.best_val_loss,
            'best_val_nrmse':    self.best_val_nrmse,
            'final_train_loss':  self.train_losses[-1]  if self.train_losses  else None,
            'final_val_loss':    self.val_losses[-1]    if self.val_losses    else None,
            'final_train_nrmse': self.train_nrmses[-1]  if self.train_nrmses  else None,
            'final_val_nrmse':   self.val_nrmses[-1]    if self.val_nrmses    else None,
            'experiment_dir':    self.experiment_dir,
            'total_epochs':      len(self.train_losses),
        }


# ===================== Main Fine-tuning Script =====================

if __name__ == '__main__':
    import argparse
    from dataloader_finetune_challenge1 import EEGFinetuneDataset
    from pretrain_model import EEGFoundationModel

    parser = argparse.ArgumentParser(description='Challenge 1: RT Prediction Fine-tuning')

    # Data
    parser.add_argument('--data_dir',            type=str,   default='D:/EEGChallenge')
    parser.add_argument('--pretrain_checkpoint', type=str,   required=True,
                        help='Path to pretrain best_model.pt')

    # Model architecture — must match the pre-trained checkpoint
    parser.add_argument('--d_model',          type=int,   default=128)
    parser.add_argument('--n_heads',          type=int,   default=4)
    parser.add_argument('--n_encoder_layers', type=int,   default=4)
    parser.add_argument('--n_decoder_layers', type=int,   default=2)
    parser.add_argument('--dim_feedforward',  type=int,   default=512)
    parser.add_argument('--dropout',          type=float, default=0.1)
    parser.add_argument('--patch_size',       type=int,   default=50)

    # Training
    parser.add_argument('--batch_size',          type=int,   default=64)
    parser.add_argument('--learning_rate',       type=float, default=1e-4)
    parser.add_argument('--epochs',              type=int,   default=100)
    parser.add_argument('--weight_decay',        type=float, default=1e-4)
    parser.add_argument('--patience',            type=int,   default=20)
    parser.add_argument('--checkpoint_interval', type=int,   default=10)
    parser.add_argument('--freeze_encoder',      action='store_true',  default=True)
    parser.add_argument('--unfreeze_encoder',    dest='freeze_encoder', action='store_false')

    # Window
    parser.add_argument('--window_length_s',    type=float, default=2.0)
    parser.add_argument('--stimulus_offset_s',  type=float, default=0.5)

    args = parser.parse_args()

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    finetune_config = vars(args)
    finetune_config['device'] = device

    print(f"Using device: {device}")

    # ── Load pre-trained model ───────────────────────────────────────────────
    print(f"\nLoading pre-trained model from: {args.pretrain_checkpoint}")
    checkpoint = torch.load(args.pretrain_checkpoint, map_location=device)

    model = EEGFoundationModel(
        n_channels=129,
        patch_size=args.patch_size,
        d_model=args.d_model,
        n_heads=args.n_heads,
        n_encoder_layers=args.n_encoder_layers,
        n_decoder_layers=args.n_decoder_layers,
        dim_feedforward=args.dim_feedforward,
        dropout=args.dropout,
    ).to(device)

    model.load_state_dict(checkpoint['model_state_dict'], strict=False)
    print("Pre-trained weights loaded successfully!")

    # ── Datasets ─────────────────────────────────────────────────────────────
    root_dirs = [
        os.path.join(args.data_dir, d) for d in os.listdir(args.data_dir)
        if os.path.isdir(os.path.join(args.data_dir, d)) and d.startswith('R')
    ]
    np.random.shuffle(root_dirs)
    split_idx  = int(0.8 * len(root_dirs))
    train_dirs = root_dirs[:split_idx]
    val_dirs   = root_dirs[split_idx:]

    print(f"\nTraining dirs: {len(train_dirs)}, Validation dirs: {len(val_dirs)}")

    train_dataset = EEGFinetuneDataset(
        train_dirs,
        window_length_s=args.window_length_s,
        stimulus_offset_s=args.stimulus_offset_s,
        tasks=['contrastChangeDetection'],
    )
    val_dataset = EEGFinetuneDataset(
        val_dirs,
        window_length_s=args.window_length_s,
        stimulus_offset_s=args.stimulus_offset_s,
        tasks=['contrastChangeDetection'],
    )

    print(f"Training windows: {len(train_dataset)}, Validation windows: {len(val_dataset)}")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True,
                              num_workers=0, pin_memory=False)
    val_loader   = DataLoader(val_dataset,   batch_size=args.batch_size, shuffle=False,
                              num_workers=0, pin_memory=False)

    # ── Optimizer ────────────────────────────────────────────────────────────
    params_to_optimize = (
        [p for p in model.parameters() if p.requires_grad]
        if args.freeze_encoder else model.parameters()
    )
    optimizer = torch.optim.AdamW(params_to_optimize,
                                  lr=args.learning_rate, weight_decay=args.weight_decay)

    # ── Train ─────────────────────────────────────────────────────────────────
    trainer = EEGFinetuneTrainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        optimizer=optimizer,
        device=device,
        config=finetune_config,
        freeze_encoder=args.freeze_encoder,
    )

    results = trainer.train(args.epochs)

    print(f"\nFine-tuning completed!")
    print(f"Best validation NRMSE: {results['best_val_nrmse']:.4f}")
    print(f"Best validation loss:  {results['best_val_loss']:.6f}")
    print(f"Results saved in:      {results['experiment_dir']}")

    inference_bundle = {
        'model_state_dict': model.state_dict(),
        'model_config': {
            'n_channels':       129,
            'patch_size':       args.patch_size,
            'd_model':          args.d_model,
            'n_heads':          args.n_heads,
            'n_encoder_layers': args.n_encoder_layers,
            'n_decoder_layers': args.n_decoder_layers,
            'dim_feedforward':  args.dim_feedforward,
            'dropout':          args.dropout,
        },
        'task_name':        'rt_prediction',
        'task_type':        'regression',
        'normalization':    'zscore',
        'window_length_s':  args.window_length_s,
        'stimulus_offset_s': args.stimulus_offset_s,
        'sfreq':            100,
        'best_val_nrmse':   results['best_val_nrmse'],
        'best_val_loss':    results['best_val_loss'],
    }
    bundle_path = os.path.join(results['experiment_dir'], 'weights_challenge_1.pt')
    torch.save(inference_bundle, bundle_path)
    print(f"Submission weights saved: {bundle_path}")
