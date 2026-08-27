# challenge2_finetune.py
# Fine-tuning pipeline for externalizing factor prediction (Challenge 2)

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
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
import warnings

warnings.filterwarnings('ignore')

from dataloader_challenge2 import ExternalizingFineTuneDataset, externalizing_collate_fn
from pretrain_model import EEGFoundationModel


class ExternalizingFinetuneTrainer:
    """
    Trainer for externalizing factor prediction using pre-trained transformer.
    """

    def __init__(self, model, train_loader, val_loader, optimizer, device, config, freeze_encoder=True):
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.optimizer = optimizer
        self.device = device
        self.config = config
        self.freeze_encoder = freeze_encoder

        if 'externalizing' not in self.model.task_heads:
            self.model.add_task_head('externalizing', 'regression', output_dim=1)

        if freeze_encoder:
            self._freeze_encoder()

        self.criterion = nn.MSELoss()

        self.train_losses = []
        self.val_losses = []
        self.train_maes = []
        self.val_maes = []
        self.train_r2s = []
        self.val_r2s = []
        self.train_nrmses = []
        self.val_nrmses = []
        self.learning_rates = []

        self.best_val_nrmse = float('inf')
        self.best_val_loss = float('inf')
        self.patience_counter = 0

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        freeze_str = 'frozen' if freeze_encoder else 'unfrozen'
        output_dir = config.get('output_dir', 'D:/eegchallenge_results')
        self.experiment_dir = os.path.join(output_dir, f"challenge2_externalizing_{freeze_str}_{timestamp}")
        os.makedirs(self.experiment_dir, exist_ok=True)

    def _freeze_encoder(self):
        print("Freezing encoder weights — only training externalizing head")
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
            print(f"  Best model saved — Val NRMSE: {self.best_val_nrmse:.4f}")

    def train_epoch(self):
        self.model.train()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        num_batches = 0

        train_bar = tqdm(self.train_loader, desc='Training')
        for batch in train_bar:
            eeg          = batch['eeg'].to(self.device)           # (B, C, T)
            externalizing = batch['externalizing'].to(self.device) # (B,)

            self.optimizer.zero_grad()

            output = self.model(eeg, mode='finetune', task_name='externalizing')
            prediction = output['prediction'].squeeze(-1)

            loss = self.criterion(prediction, externalizing)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            total_loss += loss.item()
            all_predictions.extend(prediction.detach().cpu().numpy())
            all_targets.extend(externalizing.cpu().numpy())
            num_batches += 1

            train_bar.set_postfix({
                'Loss':   f"{loss.item():.4f}",
                'Pred':   f"{prediction.mean().item():.3f}",
                'Target': f"{externalizing.mean().item():.3f}"
            })

        epoch_loss = total_loss / num_batches
        epoch_mae  = mean_absolute_error(all_targets, all_predictions)
        epoch_r2   = r2_score(all_targets, all_predictions)
        epoch_rmse = root_mean_squared_error(all_targets, all_predictions)
        epoch_nrmse = epoch_rmse / (np.std(all_targets) + 1e-8)

        return epoch_loss, epoch_mae, epoch_r2, epoch_nrmse

    def validate(self):
        self.model.eval()
        total_loss = 0.0
        all_predictions = []
        all_targets = []
        all_subject_ids = []
        num_batches = 0

        with torch.no_grad():
            val_bar = tqdm(self.val_loader, desc='Validation')
            for batch in val_bar:
                eeg           = batch['eeg'].to(self.device)
                externalizing = batch['externalizing'].to(self.device)
                subject_ids   = batch['subject_id']

                output = self.model(eeg, mode='finetune', task_name='externalizing')
                prediction = output['prediction'].squeeze(-1)

                loss = self.criterion(prediction, externalizing)

                total_loss += loss.item()
                all_predictions.extend(prediction.cpu().numpy())
                all_targets.extend(externalizing.cpu().numpy())
                all_subject_ids.extend(subject_ids)
                num_batches += 1

                val_bar.set_postfix({'Val_Loss': f"{loss.item():.4f}"})

        # Window-level metrics
        val_loss  = total_loss / num_batches
        val_mae   = mean_absolute_error(all_targets, all_predictions)
        val_r2    = r2_score(all_targets, all_predictions)
        val_rmse  = root_mean_squared_error(all_targets, all_predictions)
        val_nrmse = val_rmse / (np.std(all_targets) + 1e-8)

        # Subject-level metrics: average window predictions per subject
        subj_pred_map: dict = {}
        subj_tgt_map: dict  = {}
        for sid, pred, tgt in zip(all_subject_ids, all_predictions, all_targets):
            subj_pred_map.setdefault(sid, []).append(pred)
            subj_tgt_map[sid] = tgt  # same label for all windows of a subject

        subj_preds   = np.array([np.mean(subj_pred_map[s]) for s in subj_pred_map])
        subj_targets = np.array([subj_tgt_map[s]           for s in subj_pred_map])

        subj_rmse  = root_mean_squared_error(subj_targets, subj_preds)
        subj_nrmse = subj_rmse / (np.std(subj_targets) + 1e-8)

        return val_loss, val_mae, val_r2, val_nrmse, subj_nrmse, all_predictions, all_targets

    def train(self, epochs):
        print(f"\nStarting Challenge 2: Externalizing Factor Prediction")
        print(f"Experiment directory: {self.experiment_dir}")
        print(f"Training samples: {len(self.train_loader.dataset)}")
        print(f"Validation samples: {len(self.val_loader.dataset)}")
        print(f"Freeze encoder: {self.freeze_encoder}")
        print("-" * 80)

        self.save_config()

        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode='min',
            factor=0.5,
            patience=10,
            min_lr=1e-6,
        )

        for epoch in range(epochs):
            start_time = time.time()
            print(f"\nEpoch {epoch + 1}/{epochs}")
            print("-" * 50)

            train_loss, train_mae, train_r2, train_nrmse = self.train_epoch()
            self.train_losses.append(train_loss)
            self.train_maes.append(train_mae)
            self.train_r2s.append(train_r2)
            self.train_nrmses.append(train_nrmse)

            val_loss, val_mae, val_r2, val_nrmse, val_subj_nrmse, val_preds, val_targets = self.validate()
            self.val_losses.append(val_loss)
            self.val_maes.append(val_mae)
            self.val_r2s.append(val_r2)
            self.val_nrmses.append(val_subj_nrmse)  # track subject-level NRMSE

            scheduler.step(val_subj_nrmse)
            current_lr = self.optimizer.param_groups[0]['lr']
            self.learning_rates.append(current_lr)

            epoch_time = time.time() - start_time

            print(f"\nEpoch {epoch + 1} Summary:")
            print(f"   Train: Loss={train_loss:.6f}, NRMSE={train_nrmse:.4f}, MAE={train_mae:.4f}, R²={train_r2:.4f}")
            print(f"   Val:   Loss={val_loss:.6f}, window-NRMSE={val_nrmse:.4f}, subj-NRMSE={val_subj_nrmse:.4f}, MAE={val_mae:.4f}, R²={val_r2:.4f}")
            print(f"   LR: {current_lr:.2e}, Time: {epoch_time:.2f}s")

            if val_subj_nrmse < self.best_val_nrmse:
                self.best_val_nrmse = val_subj_nrmse
                self.best_val_loss  = val_loss
                self.save_checkpoint(epoch + 1, is_best=True)
                self.patience_counter = 0
            else:
                self.patience_counter += 1

            if (epoch + 1) % 10 == 0:
                self.save_checkpoint(epoch + 1)

            if self.patience_counter >= self.config.get('patience', 20):
                print(f"\nEarly stopping triggered after {epoch + 1} epochs")
                break

        self.save_checkpoint(epochs)
        self._plot_training_curves()
        self._plot_prediction_scatter(val_preds, val_targets)

        return {
            'best_val_nrmse':     self.best_val_nrmse,
            'best_val_loss':      self.best_val_loss,
            'final_train_nrmse':  self.train_nrmses[-1],
            'final_val_nrmse':    self.val_nrmses[-1],
            'experiment_dir':     self.experiment_dir,
            'total_epochs':       len(self.train_losses),
        }

    def _plot_training_curves(self):
        _, axes = plt.subplots(1, 4, figsize=(20, 5))

        axes[0].plot(self.train_losses, label='Train', marker='o')
        axes[0].plot(self.val_losses, label='Val', marker='s')
        axes[0].set_title('MSE Loss')
        axes[0].legend(); axes[0].grid(True)

        axes[1].plot(self.train_nrmses, label='Train', marker='o', color='red')
        axes[1].plot(self.val_nrmses, label='Val', marker='s', color='darkred')
        axes[1].set_title('Normalized RMSE (Challenge Metric)')
        axes[1].legend(); axes[1].grid(True)

        axes[2].plot(self.train_maes, label='Train', marker='o')
        axes[2].plot(self.val_maes, label='Val', marker='s')
        axes[2].set_title('Mean Absolute Error')
        axes[2].legend(); axes[2].grid(True)

        axes[3].plot(self.train_r2s, label='Train', marker='o')
        axes[3].plot(self.val_r2s, label='Val', marker='s')
        axes[3].set_title('R² Score')
        axes[3].legend(); axes[3].grid(True)

        plt.tight_layout()
        plt.savefig(os.path.join(self.experiment_dir, "training_curves.png"), dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_prediction_scatter(self, predictions, targets):
        plt.figure(figsize=(8, 8))
        plt.scatter(targets, predictions, alpha=0.5)

        min_val = min(min(targets), min(predictions))
        max_val = max(max(targets), max(predictions))
        plt.plot([min_val, max_val], [min_val, max_val], 'r--', label='Perfect Prediction')

        plt.xlabel('Actual Externalizing')
        plt.ylabel('Predicted Externalizing')
        plt.title('Externalizing Prediction: Actual vs Predicted')
        plt.legend()
        plt.grid(True, alpha=0.3)

        plt.savefig(os.path.join(self.experiment_dir, "prediction_scatter.png"), dpi=300, bbox_inches='tight')
        plt.close()


def split_dataset_by_subject(dataset, train_ratio=0.8, seed=42):
    """Split dataset by subject to prevent data leakage."""
    np.random.seed(seed)

    all_subjects = list(set([item[2] for item in dataset.windows]))
    np.random.shuffle(all_subjects)

    split_idx = int(len(all_subjects) * train_ratio)
    train_subjects = set(all_subjects[:split_idx])
    val_subjects   = set(all_subjects[split_idx:])

    train_indices = [i for i, item in enumerate(dataset.windows) if item[2] in train_subjects]
    val_indices   = [i for i, item in enumerate(dataset.windows) if item[2] in val_subjects]

    train_dataset = Subset(dataset, train_indices)
    val_dataset   = Subset(dataset, val_indices)

    print(f"Train subjects: {len(train_subjects)}, Val subjects: {len(val_subjects)}")
    print(f"Train windows: {len(train_indices)}, Val windows: {len(val_indices)}")

    return train_dataset, val_dataset


# ===================== Main Execution =====================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Challenge 2: Externalizing Factor Fine-tuning')

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
    parser.add_argument('--batch_size',            type=int,   default=64)
    parser.add_argument('--learning_rate',         type=float, default=1e-4)
    parser.add_argument('--epochs',                type=int,   default=100)
    parser.add_argument('--weight_decay',          type=float, default=1e-4)
    parser.add_argument('--patience',              type=int,   default=20)
    parser.add_argument('--n_windows_per_subject', type=int,   default=20)
    parser.add_argument('--freeze_encoder',        action='store_true',  default=True)
    parser.add_argument('--unfreeze_encoder',      dest='freeze_encoder', action='store_false')
    parser.add_argument('--output_dir',            type=str,   default='D:/eegchallenge_results',
                        help='Root directory for experiment outputs')

    args = parser.parse_args()

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    config = vars(args)
    config['device'] = device

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

    # ── Dataset ──────────────────────────────────────────────────────────────
    root_dirs = [
        os.path.join(args.data_dir, d) for d in os.listdir(args.data_dir)
        if os.path.isdir(os.path.join(args.data_dir, d)) and d.startswith('R')
    ]
    print(f"\nFound {len(root_dirs)} directories")

    full_dataset = ExternalizingFineTuneDataset(
        root_dirs=root_dirs,
        window_length_s=2.0,
        sfreq=100,
        n_windows_per_subject=args.n_windows_per_subject,
        tasks=None,
    )

    train_dataset, val_dataset = split_dataset_by_subject(full_dataset, train_ratio=0.8)

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True,
        collate_fn=externalizing_collate_fn, num_workers=0, pin_memory=False,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False,
        collate_fn=externalizing_collate_fn, num_workers=0, pin_memory=False,
    )

    # ── Optimizer ────────────────────────────────────────────────────────────
    params_to_optimize = (
        [p for p in model.parameters() if p.requires_grad]
        if args.freeze_encoder else model.parameters()
    )
    optimizer = torch.optim.AdamW(params_to_optimize,
                                  lr=args.learning_rate, weight_decay=args.weight_decay)

    # ── Train ─────────────────────────────────────────────────────────────────
    trainer = ExternalizingFinetuneTrainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        optimizer=optimizer,
        device=device,
        config=config,
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
        'task_name':             'externalizing',
        'task_type':             'regression',
        'normalization':         'zscore',
        'n_windows_per_subject': args.n_windows_per_subject,
        'sfreq':                 100,
        'best_val_subj_nrmse':   results['best_val_nrmse'],  # subject-level (competition metric)
        'best_val_loss':         results['best_val_loss'],
    }
    bundle_path = os.path.join(results['experiment_dir'], 'weights_challenge_2.pt')
    torch.save(inference_bundle, bundle_path)
    print(f"Submission weights saved: {bundle_path}")
