import torch
import torch.nn as nn
import numpy as np
import os
import time
from datetime import datetime
import json
import warnings
from torch.utils.data import DataLoader
import matplotlib.pyplot as plt
from tqdm import tqdm

warnings.filterwarnings('ignore')

from EEG_Competition.pretrain_dataloader import EEGPretrainDataset, pretrain_collate_fn
from EEG_Competition.Pretrain_Model import EEGFoundationModel, MultiTaskPretrainLoss

# complete_training_with_vicreg.py
# Drop-in replacement for your current training script
# Just set use_vicreg=True in config


class EEGFoundationTrainer:
    def __init__(self, model, train_loader, val_loader, optimizer, criterion, device, config):
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.optimizer = optimizer
        self.criterion = criterion
        self.device = device
        self.config = config

        # Training history
        self.train_losses = []
        self.val_losses = []
        self.train_recon_losses = []
        self.train_contrast_losses = []
        self.val_recon_losses = []
        self.val_contrast_losses = []
        self.vicreg_history = []  # Track VICReg components
        self.learning_rates = []

        # Best model tracking
        self.best_val_loss = float('inf')
        self.best_model_state = None
        self.patience_counter = 0

        # Create experiment directory
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        method = 'vicreg' if config.get('use_vicreg', False) else 'ntxent'
        self.experiment_dir = f"homedir/analysis/derivatives/pretraining_{method}_{timestamp}"
        os.makedirs(self.experiment_dir, exist_ok=True)

    def save_config(self):
        import json
        config_path = os.path.join(self.experiment_dir, "training_config.json")
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def save_checkpoint(self, epoch, is_best=False):
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'train_losses': self.train_losses,
            'val_losses': self.val_losses,
            'best_val_loss': self.best_val_loss,
            'config': self.config
        }

        checkpoint_path = os.path.join(self.experiment_dir, f"checkpoint_epoch_{epoch:04d}.pt")
        torch.save(checkpoint, checkpoint_path)

        if is_best:
            best_path = os.path.join(self.experiment_dir, "best_model.pt")
            torch.save(checkpoint, best_path)
            print(f"  Best model saved with val_loss: {self.best_val_loss:.6f}")

    def _generate_random_mask(self, n_patches, mask_ratio=0.6):
        """Generate random mask for MAE"""
        n_mask = int(n_patches * mask_ratio)
        indices = torch.randperm(n_patches)
        mask = torch.zeros(n_patches, dtype=torch.bool)
        mask[indices[:n_mask]] = True
        return mask.to(self.device)

    def train_epoch(self):
        """Train one epoch"""
        self.model.train()
        total_loss = 0.0
        total_recon_loss = 0.0
        total_contrast_loss = 0.0
        num_batches = 0

        # Track VICReg components
        vicreg_stats = {'sim': [], 'var': [], 'cov': []}

        train_bar = tqdm(self.train_loader, desc='Training')
        for batch_idx, data in enumerate(train_bar):
            data = data.to(self.device)

            # Generate mask
            batch_size, n_channels, seq_len = data.shape
            n_patches = seq_len // self.model.patch_size
            mask = self._generate_random_mask(n_patches, mask_ratio=0.6)

            self.optimizer.zero_grad()

            # Two forward passes for contrastive learning
            output1 = self.model(data, mode='pretrain')
            output2 = self.model(data, mode='pretrain')

            # Calculate loss
            loss_dict = self.criterion(
                original=data,
                reconstructed=output1['reconstructed'],
                pooled1=output1['pooled'],
                pooled2=output2['pooled'],
                mask=mask,
                n_patches=n_patches,
                patch_size=self.model.patch_size
            )

            loss_dict['total_loss'].backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            # Accumulate statistics
            total_loss += loss_dict['total_loss'].item()
            total_recon_loss += loss_dict['reconstruction_loss'].item()
            total_contrast_loss += loss_dict['contrastive_loss'].item()
            num_batches += 1

            # Track VICReg stats if available
            if 'contrast_stats' in loss_dict and loss_dict['contrast_stats']:
                stats = loss_dict['contrast_stats']
                vicreg_stats['sim'].append(stats.get('sim_loss', 0))
                vicreg_stats['var'].append(stats.get('var_loss', 0))
                vicreg_stats['cov'].append(stats.get('cov_loss', 0))

                train_bar.set_postfix({
                    'Loss': f"{loss_dict['total_loss'].item():.4f}",
                    'Recon': f"{loss_dict['reconstruction_loss'].item():.4f}",
                    'Sim': f"{stats.get('sim_loss', 0):.4f}",
                    'Var': f"{stats.get('var_loss', 0):.4f}",
                    'Cov': f"{stats.get('cov_loss', 0):.4f}"
                })
            else:
                train_bar.set_postfix({
                    'Loss': f"{loss_dict['total_loss'].item():.4f}",
                    'Recon': f"{loss_dict['reconstruction_loss'].item():.4f}",
                    'Contrast': f"{loss_dict['contrastive_loss'].item():.4f}"
                })

        epoch_loss = total_loss / num_batches
        epoch_recon_loss = total_recon_loss / num_batches
        epoch_contrast_loss = total_contrast_loss / num_batches

        # Store VICReg stats if available
        if vicreg_stats['sim']:
            vicreg_epoch_stats = {
                'sim': np.mean(vicreg_stats['sim']),
                'var': np.mean(vicreg_stats['var']),
                'cov': np.mean(vicreg_stats['cov'])
            }
            return epoch_loss, epoch_recon_loss, epoch_contrast_loss, vicreg_epoch_stats

        return epoch_loss, epoch_recon_loss, epoch_contrast_loss, {}

    def validate(self):
        """Validation phase"""
        self.model.eval()
        total_loss = 0.0
        total_recon_loss = 0.0
        total_contrast_loss = 0.0
        num_batches = 0

        with torch.no_grad():
            val_bar = tqdm(self.val_loader, desc='Validation')
            for data in val_bar:
                data = data.to(self.device)

                # Generate mask
                batch_size, n_channels, seq_len = data.shape
                n_patches = seq_len // self.model.patch_size
                mask = self._generate_random_mask(n_patches, mask_ratio=0.6)

                # Two forward passes
                output1 = self.model(data, mode='pretrain')
                output2 = self.model(data, mode='pretrain')

                # Calculate loss
                loss_dict = self.criterion(
                    original=data,
                    reconstructed=output1['reconstructed'],
                    pooled1=output1['pooled'],
                    pooled2=output2['pooled'],
                    mask=mask,
                    n_patches=n_patches,
                    patch_size=self.model.patch_size
                )

                total_loss += loss_dict['total_loss'].item()
                total_recon_loss += loss_dict['reconstruction_loss'].item()
                total_contrast_loss += loss_dict['contrastive_loss'].item()
                num_batches += 1

                val_bar.set_postfix({
                    'Val_Loss': f"{loss_dict['total_loss'].item():.4f}",
                    'Recon': f"{loss_dict['reconstruction_loss'].item():.4f}"
                })

        val_loss = total_loss / num_batches
        val_recon_loss = total_recon_loss / num_batches
        val_contrast_loss = total_contrast_loss / num_batches

        return val_loss, val_recon_loss, val_contrast_loss

    def train(self, epochs):
        """Main training loop"""
        method = 'VICReg' if self.config.get('use_vicreg', False) else 'NT-Xent'
        print(f"\nStarting EEG Foundation Model Pre-training with {method}")
        print(f"Experiment directory: {self.experiment_dir}")
        print(f"Training samples: {len(self.train_loader.dataset)}")
        print(f"Validation samples: {len(self.val_loader.dataset)}")
        print("-" * 80)

        self.save_config()

        # Cosine scheduler
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=epochs, eta_min=1e-6
        )

        for epoch in range(epochs):
            import time
            start_time = time.time()

            print(f"\nEpoch {epoch + 1}/{epochs}")
            print("-" * 50)

            # Training
            result = self.train_epoch()
            if len(result) == 4:
                train_loss, train_recon, train_contrast, vicreg_stats = result
                self.vicreg_history.append(vicreg_stats)
            else:
                train_loss, train_recon, train_contrast = result
                vicreg_stats = {}

            self.train_losses.append(train_loss)
            self.train_recon_losses.append(train_recon)
            self.train_contrast_losses.append(train_contrast)

            # Validation
            val_loss, val_recon, val_contrast = self.validate()
            self.val_losses.append(val_loss)
            self.val_recon_losses.append(val_recon)
            self.val_contrast_losses.append(val_contrast)

            # Update learning rate
            scheduler.step()
            current_lr = self.optimizer.param_groups[0]['lr']
            self.learning_rates.append(current_lr)

            epoch_time = time.time() - start_time

            # Epoch summary
            print(f"\nEpoch {epoch + 1} Summary:")
            print(f"   Train Loss: {train_loss:.6f} (Recon: {train_recon:.6f}, Contrast: {train_contrast:.6f})")
            if vicreg_stats:
                print(
                    f"   VICReg: Sim={vicreg_stats['sim']:.4f}, Var={vicreg_stats['var']:.4f}, Cov={vicreg_stats['cov']:.4f}")
            print(f"   Val Loss:   {val_loss:.6f} (Recon: {val_recon:.6f}, Contrast: {val_contrast:.6f})")
            print(f"   Learning Rate: {current_lr:.2e}")
            print(f"   Time: {epoch_time:.2f}s")

            # Model selection
            if val_loss < self.best_val_loss:
                self.best_val_loss = val_loss
                self.best_model_state = self.model.state_dict().copy()
                self.save_checkpoint(epoch + 1, is_best=True)
                self.patience_counter = 0
            else:
                self.patience_counter += 1

            # Periodic checkpoint
            if (epoch + 1) % 10 == 0:
                self.save_checkpoint(epoch + 1)

            # Early stopping
            if self.patience_counter >= self.config.get('patience', 15):
                print(f"\nEarly stopping triggered after {epoch + 1} epochs")
                break

        # Final save
        self.save_checkpoint(epochs)
        self._plot_training_curves()

        return {
            'best_val_loss': self.best_val_loss,
            'final_train_loss': self.train_losses[-1],
            'final_val_loss': self.val_losses[-1],
            'experiment_dir': self.experiment_dir,
            'total_epochs': len(self.train_losses)
        }

    def _plot_training_curves(self):
        """Plot training curves"""
        if self.vicreg_history:
            # VICReg plots
            fig, axes = plt.subplots(2, 3, figsize=(18, 10))

            # Total loss
            axes[0, 0].plot(self.train_losses, label='Train', marker='o')
            axes[0, 0].plot(self.val_losses, label='Val', marker='s')
            axes[0, 0].set_title('Total Loss')
            axes[0, 0].legend()
            axes[0, 0].grid(True)

            # Reconstruction
            axes[0, 1].plot(self.train_recon_losses, label='Train', marker='o')
            axes[0, 1].plot(self.val_recon_losses, label='Val', marker='s')
            axes[0, 1].set_title('Reconstruction Loss')
            axes[0, 1].legend()
            axes[0, 1].grid(True)

            # Contrastive
            axes[0, 2].plot(self.train_contrast_losses, label='Train', marker='o')
            axes[0, 2].plot(self.val_contrast_losses, label='Val', marker='s')
            axes[0, 2].set_title('Contrastive Loss')
            axes[0, 2].legend()
            axes[0, 2].grid(True)

            # VICReg components
            sim = [v['sim'] for v in self.vicreg_history]
            var = [v['var'] for v in self.vicreg_history]
            cov = [v['cov'] for v in self.vicreg_history]

            axes[1, 0].plot(sim, marker='o', color='blue')
            axes[1, 0].set_title('VICReg: Invariance (Similarity)')
            axes[1, 0].grid(True)

            axes[1, 1].plot(var, marker='o', color='orange')
            axes[1, 1].set_title('VICReg: Variance')
            axes[1, 1].grid(True)

            axes[1, 2].plot(cov, marker='o',color='green')
            axes[1, 2].set_title('VICReg: Covariance')
            axes[1, 2].grid(True)

            plt.tight_layout()
        else:
            # Standard plots
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))

            axes[0].plot(self.train_losses, label='Train', marker='o')
            axes[0].plot(self.val_losses, label='Val', marker='s')
            axes[0].set_title('Total Loss')
            axes[0].legend()
            axes[0].grid(True)

            axes[1].plot(self.train_recon_losses, label='Train', marker='o')
            axes[1].plot(self.val_recon_losses, label='Val', marker='s')
            axes[1].set_title('Reconstruction Loss')
            axes[1].legend()
            axes[1].grid(True)

            axes[2].plot(self.train_contrast_losses, label='Train', marker='o')
            axes[2].plot(self.val_contrast_losses, label='Val', marker='s')
            axes[2].set_title('Contrastive Loss')
            axes[2].legend()
            axes[2].grid(True)

            plt.tight_layout()

        plot_path = os.path.join(self.experiment_dir, "training_curves.png")
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()


# ===================== Main Execution =====================

if __name__ == '__main__':
    # Configuration
    config = {
        'batch_size': 128,
        'learning_rate': 0.001,
        'epochs': 1000,
        'weight_decay': 1e-4,
        'patience': 20,
        'reconstruction_weight': 1.0,
        'contrastive_weight': 0.5,
        'mask_ratio': 0.6,
        'use_vicreg': True,  # <-- SET THIS: True=VICReg, False=NT-Xent
        'device': 'cuda' if torch.cuda.is_available() else 'cpu'
    }

    print(f"Using device: {config['device']}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name()}")

    # Data Loading
    base_path = 'homedir/sourcedata/'
    root_dirs = [os.path.join(base_path, d) for d in os.listdir(base_path)
                 if os.path.isdir(os.path.join(base_path, d)) and d.startswith('R')]

    val_dir = np.random.choice(root_dirs)
    train_dirs = [d for d in root_dirs if d != val_dir]

    print(f"\nTraining directories: {len(train_dirs)}")
    print(f"Validation directory: {val_dir}")

    # Create datasets
    train_dataset = EEGPretrainDataset(train_dirs, tasks=['surroundSupp'])
    val_dataset = EEGPretrainDataset([val_dir], tasks=['surroundSupp'])

    # Create data loaders
    train_loader = DataLoader(
        train_dataset,
        batch_size=config['batch_size'],
        shuffle=True,
        collate_fn=pretrain_collate_fn,
        num_workers=0,
        pin_memory=False
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=config['batch_size'],
        shuffle=False,
        collate_fn=pretrain_collate_fn,
        num_workers=0,
        pin_memory=False
    )

    # Model Setup
    model = EEGFoundationModel(
        n_channels=129,
        patch_size=50,
        d_model=256,
        n_heads=8,
        n_encoder_layers=6,
        n_decoder_layers=6,
        dim_feedforward=2048,
        dropout=0.3
    ).to(config['device'])

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\nModel Parameters:")
    print(f"   Total: {total_params:,}")
    print(f"   Trainable: {trainable_params:,}")

    # Loss & Optimizer
    criterion = MultiTaskPretrainLoss(
        reconstruction_weight=config['reconstruction_weight'],
        contrastive_weight=config['contrastive_weight'],
        use_vicreg=config['use_vicreg']  # Pass VICReg flag
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config['learning_rate'],
        weight_decay=config['weight_decay'],
        betas=(0.9, 0.999)
    )

    # Training
    trainer = EEGFoundationTrainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        optimizer=optimizer,
        criterion=criterion,
        device=config['device'],
        config=config
    )

    results = trainer.train(config['epochs'])

    print(f"\nTraining completed!")
    print(f"Best validation loss: {results['best_val_loss']:.6f}")
    print(f"Results saved in: {results['experiment_dir']}")
