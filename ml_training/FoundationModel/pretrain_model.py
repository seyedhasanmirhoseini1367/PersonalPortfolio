# pretrain_model.py
# EEG Foundation Model with Patch-Channel Cross-Attention fusion

import math
from typing import Optional
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist

# ---------------------------
# Positional encoding
# ---------------------------
class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 10000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() *
                             (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # shape (1, max_len, d_model)
        self.register_buffer('pe', pe)
        self.max_len = max_len

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, d_model) because we use batch_first=True in transformers
        seq_len = x.size(1)
        if seq_len > self.max_len:
            raise ValueError(f"Sequence length {seq_len} > max_len {self.max_len}")
        return x + self.pe[:, :seq_len, :]


# ---------------------------
# Channel attention (SE-style)
# ---------------------------
class ChannelAttention(nn.Module):
    def __init__(self, n_channels: int, reduction: int = 16):
        super().__init__()
        self.avg_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)
        self.fc = nn.Sequential(
            nn.Linear(n_channels, n_channels // reduction, bias=False),
            nn.ReLU(),
            nn.Linear(n_channels // reduction, n_channels, bias=False)
        )
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        # x: (batch, channels, time)
        avg_out = self.fc(self.avg_pool(x).squeeze(-1))
        max_out = self.fc(self.max_pool(x).squeeze(-1))
        out = self.sigmoid(avg_out + max_out).unsqueeze(-1)
        return x * out


# ---------------------------
# Patch embedding
# ---------------------------
class EEGPatchEmbedding(nn.Module):
    def __init__(self, n_channels: int = 129, patch_size: int = 25, d_model: int = 512):
        super().__init__()
        self.n_channels = n_channels
        self.patch_size = patch_size
        self.d_model = d_model
        self.channel_attention = ChannelAttention(n_channels)
        self.patch_proj = nn.Linear(n_channels * patch_size, d_model)
        self.channel_embed = nn.Parameter(torch.randn(n_channels, d_model))

    def forward(self, x: torch.Tensor):
        # x: (batch, channels, time)
        batch_size, n_channels, seq_len = x.shape
        x = self.channel_attention(x)
        n_patches = seq_len // self.patch_size
        if seq_len % self.patch_size != 0:
            pad_len = self.patch_size - (seq_len % self.patch_size)
            x = F.pad(x, (0, pad_len))
            n_patches += 1
        # reshape to (batch, n_patches, channels * patch_size)
        x = x.reshape(batch_size, n_channels, n_patches, self.patch_size)
        x = x.permute(0, 2, 1, 3) # reshape to (batch, n_patches, channels, patch_size)
        x = x.reshape(batch_size, n_patches, n_channels * self.patch_size)
        x = self.patch_proj(x)
        channel_info = self.channel_embed.mean(0).unsqueeze(0).unsqueeze(0)
        x = x + channel_info
        return x, n_patches


# ---------------------------
# Patch-Channel Fusion via Cross-Attention
# ---------------------------
class PatchChannelFusion(nn.Module):
    """
    Cross-attention fusion: queries = patch tokens, keys/values = channel tokens.
    Accepts channel tokens as a parameter (n_channels, d_model) and expands to batch if needed.
    Returns fused patch tokens and attention weights.
    """
    def __init__(self, n_channels: int, d_model: int, n_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        self.n_channels = n_channels
        self.d_model = d_model
        self.n_heads = n_heads
        # MultiheadAttention with batch_first=True for (B, L, E) inputs
        self.cross_attn = nn.MultiheadAttention(embed_dim=d_model, num_heads=n_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.LayerNorm(d_model)
        self.mlp = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
            nn.Dropout(dropout)
        )
        self.norm2 = nn.LayerNorm(d_model)

    def forward(self, x_patches: torch.Tensor, channel_tokens: torch.Tensor):
        """
        x_patches: (B, n_patches, d_model)
        channel_tokens: (n_channels, d_model) or (B, n_channels, d_model)
        Returns: fused_patches (B, n_patches, d_model), attn_weights (B, n_patches, n_channels)
        """
        B, n_patches, _ = x_patches.shape

        # Prepare keys/values from channel_tokens
        if channel_tokens.dim() == 2:
            keys = channel_tokens.unsqueeze(0).expand(B, -1, -1)  # (B, n_channels, d_model)
        elif channel_tokens.dim() == 3:
            keys = channel_tokens  # (B, n_channels, d_model)
        else:
            raise ValueError("channel_tokens must be (n_channels, d_model) or (B, n_channels, d_model)")

        # MultiheadAttention expects (B, L, E) with batch_first=True
        attn_out, attn_weights = self.cross_attn(query=x_patches, key=keys, value=keys)
        # attn_out: (B, n_patches, d_model), attn_weights: (B, n_patches, n_channels)

        # Residual + norm + MLP
        x = x_patches + attn_out
        x = self.norm1(x)
        x = x + self.mlp(x)
        x = self.norm2(x)

        return x, attn_weights


# ---------------------------
# Foundation model (Transformer AE)
# ---------------------------
class EEGFoundationModel(nn.Module):
    def __init__(
        self,
        n_channels: int = 129,
        patch_size: int = 25,
        d_model: int = 512,
        n_heads: int = 8,
        n_encoder_layers: int = 6,
        n_decoder_layers: int = 6,
        dim_feedforward: int = 2048,
        dropout: float = 0.1,
        max_seq_len: int = 10000,
        use_demographics: bool = False,
        n_demographic_features: int = 3,
    ):
        super().__init__()
        self.d_model = d_model
        self.patch_size = patch_size
        self.patch_embed = EEGPatchEmbedding(n_channels, patch_size, d_model)
        # fusion module added (cross-attention)
        self.fusion = PatchChannelFusion(n_channels=n_channels, d_model=d_model, n_heads=n_heads, dropout=dropout)
        self.pos_encoding = PositionalEncoding(d_model, max_seq_len)
        self.use_demographics = use_demographics
        if use_demographics:
            self.demo_proj = nn.Linear(n_demographic_features, d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=n_heads,
                                                   dim_feedforward=dim_feedforward,
                                                   dropout=dropout, batch_first=True)
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_encoder_layers)
        decoder_layer = nn.TransformerDecoderLayer(d_model=d_model, nhead=n_heads,
                                                   dim_feedforward=dim_feedforward,
                                                   dropout=dropout, batch_first=True)
        self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=n_decoder_layers)
        self.reconstruct_head = nn.Linear(d_model, n_channels * patch_size)
        self.dropout = nn.Dropout(dropout)
        self.task_heads = nn.ModuleDict()

    def add_task_head(self, task_name: str, head_type: str, output_dim: int):
        if head_type in ('regression', 'classification'):
            self.task_heads[task_name] = nn.Sequential(
                nn.Linear(self.d_model, self.d_model // 2),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(self.d_model // 2, output_dim)
            )
        else:
            raise ValueError(f"head_type must be 'regression' or 'classification', got '{head_type}'")

    def forward(self, x: torch.Tensor, demographics: Optional[torch.Tensor] = None,
                mode: str = 'pretrain', task_name: Optional[str] = None):
        """
        mode:
          'pretrain' -> returns encoded, pooled, reconstructed, n_patches
          'finetune' -> expects task_name; returns prediction
          'encode' -> returns pooled only
        """
        batch_size = x.shape[0]
        # patch embedding
        x, n_patches = self.patch_embed(x)  # (batch, n_patches, d_model)

        # Fusion: cross-attention between patch tokens (queries) and channel tokens (keys/values)
        # Use the channel_embed from patch_embed as channel tokens
        fused, attn_weights = self.fusion(x, self.patch_embed.channel_embed)

        # Positional encoding on fused patch tokens
        x = self.pos_encoding(fused)  # (batch, n_patches, d_model)

        if self.use_demographics and demographics is not None:
            demo_emb = self.demo_proj(demographics).unsqueeze(1)
            x = x + demo_emb
        x = self.dropout(x)
        encoded = self.encoder(x)  # (batch, n_patches, d_model)
        pooled = encoded.mean(dim=1)  # (batch, d_model)
        if mode == 'pretrain':
            # decoder: we pass the original x as target sequence for simplicity
            decoded = self.decoder(x, encoded)
            reconstructed = self.reconstruct_head(decoded)  # (batch, n_patches, n_channels*patch_size)
            return {
                'encoded': encoded,
                'pooled': pooled,
                'reconstructed': reconstructed,
                'n_patches': n_patches,
                'attn_weights': attn_weights
            }
        elif mode == 'finetune' and task_name is not None:
            if task_name not in self.task_heads:
                raise ValueError(f"Task head {task_name} not present")
            output = self.task_heads[task_name](pooled)
            return {
                'pooled': pooled,
                'prediction': output,
                'attn_weights': attn_weights
            }
        elif mode == 'encode':
            return {'pooled': pooled, 'encoded': encoded, 'attn_weights': attn_weights}
        else:
            return {'encoded': encoded, 'pooled': pooled, 'attn_weights': attn_weights}


# ---------------------------
# Projector MLP (for contrastive)
# ---------------------------
class Projector(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int = 512, out_dim: int = 1024):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, out_dim)
        )

    def forward(self, x):
        return self.net(x)


# ---------------------------
# NT-Xent loss (SimCLR)
# ---------------------------

def nt_xent_loss(z1: torch.Tensor, z2: torch.Tensor, temperature: float = 0.1, eps: float = 1e-8):
    z1 = F.normalize(z1, dim=1)
    z2 = F.normalize(z2, dim=1)
    N = z1.shape[0]
    z = torch.cat([z1, z2], dim=0)  # (2N, D)
    sim = torch.mm(z, z.t()) / temperature

    # FIX: Create boolean mask first, then convert to float
    mask = ~torch.eye(2 * N, dtype=torch.bool, device=sim.device)
    mask = mask.float()

    exp_sim = torch.exp(sim) * mask
    # positives are diag offset by N
    positives = torch.cat([torch.diag(sim, N), torch.diag(sim, -N)], dim=0)
    nom = torch.exp(positives)
    denom = exp_sim.sum(dim=1) + eps
    loss = -torch.log(nom / denom)
    return loss.mean()


# ---------------------------
# Multi-task pretrain loss (MAE recon + NT-Xent)
# ---------------------------

class MultiTaskPretrainLoss(nn.Module):
    def __init__(self, reconstruction_weight: float = 1.0,
                 contrastive_weight: float = 0.5,
                 use_vicreg: bool = True,
                 temperature: float = 0.1):
        super().__init__()
        self.recon_w = reconstruction_weight
        self.contrast_w = contrastive_weight
        self.use_vicreg = use_vicreg
        self.temperature = temperature
        self.mse = nn.MSELoss(reduction='mean')

        if use_vicreg:
            self.contrastive_fn = VICRegLoss()
            print("Using VICReg contrastive loss")
        else:
            print("Using NT-Xent contrastive loss")

    def reconstruction_loss(self, original: torch.Tensor, reconstructed: torch.Tensor,
                            mask: torch.Tensor, n_patches: int, patch_size: int):
        
        batch_size, n_channels, seq_len = original.shape
        recon = reconstructed.reshape(batch_size, n_patches, n_channels, patch_size)
        recon = recon.permute(0, 2, 1, 3)
        recon = recon.reshape(batch_size, n_channels, n_patches * patch_size)

        if recon.shape[-1] > seq_len:
            recon = recon[:, :, :seq_len]

        tile = mask.repeat_interleave(patch_size)
        tile = tile[:seq_len].unsqueeze(0).unsqueeze(0).to(recon.device)

        if tile.sum() == 0:
            return self.mse(recon, original)

        diff = (recon - original) * tile
        loss = diff.pow(2).sum() / tile.sum()
        return loss

    def contrastive_loss_vicreg(self, pooled1: torch.Tensor, pooled2: torch.Tensor):
        """VICReg contrastive loss"""
        loss, stats = self.contrastive_fn(pooled1, pooled2)
        return loss, stats

    def contrastive_loss_ntxent(self, z1: torch.Tensor, z2: torch.Tensor):
        """Original NT-Xent loss"""
        z1 = F.normalize(z1, dim=1)
        z2 = F.normalize(z2, dim=1)

        N = z1.shape[0]
        z = torch.cat([z1, z2], dim=0)
        sim_matrix = torch.mm(z, z.t())
        sim_matrix = sim_matrix / self.temperature

        mask_eye = torch.eye(2 * N, dtype=torch.bool, device=z.device)
        mask = torch.logical_not(mask_eye).float()

        exp_sim = torch.exp(sim_matrix) * mask
        pos_sim = torch.cat([torch.diag(sim_matrix, N), torch.diag(sim_matrix, -N)], dim=0)

        numerator = torch.exp(pos_sim)
        denominator = exp_sim.sum(dim=1) + 1e-8

        loss = -torch.log(numerator / denominator)
        return loss.mean(), {}

    def forward(self, original: torch.Tensor, reconstructed: torch.Tensor,
                pooled1: torch.Tensor, pooled2: torch.Tensor,
                mask: torch.Tensor, n_patches: int, patch_size: int):

        # Reconstruction loss
        recon_loss = self.reconstruction_loss(original, reconstructed, mask, n_patches, patch_size)

        # Contrastive loss
        if self.use_vicreg:
            contrast_loss, contrast_stats = self.contrastive_loss_vicreg(pooled1, pooled2)
        else:
            contrast_loss, contrast_stats = self.contrastive_loss_ntxent(pooled1, pooled2)

        # Total loss
        total = self.recon_w * recon_loss + self.contrast_w * contrast_loss

        return {
            'total_loss': total,
            'reconstruction_loss': recon_loss.detach(),
            'contrastive_loss': contrast_loss.detach(),
            'contrast_stats': contrast_stats
        }


class VICRegLoss(nn.Module):
    """
    VICReg: Variance-Invariance-Covariance Regularization
    """

    def __init__(self, sim_weight=25.0, var_weight=40.0, cov_weight=1.0, eps=1e-4):
        super().__init__()
        self.sim_weight = sim_weight
        self.var_weight = var_weight
        self.cov_weight = cov_weight
        self.eps = eps

    def forward(self, z1, z2):
        """
        z1, z2: embeddings from two views (batch, dim)
        Returns: total loss and component stats
        """
        batch_size = z1.shape[0]
        dim = z1.shape[1]

        z1 = F.normalize(z1, dim=1)
        z2 = F.normalize(z2, dim=1)

        # Optional Distributed Gather (only if multi-GPU/large batch)
        if dist.is_available() and dist.is_initialized():
            z1_list = FullGatherLayer.apply(z1)
            z2_list = FullGatherLayer.apply(z2)
            z1 = torch.cat(z1_list, dim=0)
            z2 = torch.cat(z2_list, dim=0)
            batch_size = z1.shape[0] // dist.get_world_size()  # Global batch size

        # 1. INVARIANCE: representations should be similar
        sim_loss = F.mse_loss(z1, z2)

        # 2. VARIANCE: prevent collapse
        std_z1 = torch.sqrt(z1.var(dim=0) + self.eps)
        std_z2 = torch.sqrt(z2.var(dim=0) + self.eps)
        var_loss = (torch.mean(F.relu(1 - std_z1)) + torch.mean(F.relu(1 - std_z2))) / 2

        # 3. COVARIANCE: decorrelate features
        z1_centered = z1 - z1.mean(dim=0)
        z2_centered = z2 - z2.mean(dim=0)

        cov_z1 = (z1_centered.T @ z1_centered) / (batch_size - 1)
        cov_z2 = (z2_centered.T @ z2_centered) / (batch_size - 1)

        cov_loss = self._off_diagonal(cov_z1).pow(2).sum() / dim + \
                   self._off_diagonal(cov_z2).pow(2).sum() / dim

        # Combine
        total_loss = self.sim_weight * sim_loss + \
                     self.var_weight * var_loss + \
                     self.cov_weight * cov_loss

        return total_loss, {
            'sim_loss': sim_loss.item(),
            'var_loss': var_loss.item(),
            'cov_loss': cov_loss.item()
        }

    def _off_diagonal(self, x):
        n = x.shape[0]
        return x.flatten()[:-1].reshape(n - 1, n + 1)[:, 1:].flatten()


class VICRegProjector(nn.Module):

    def __init__(self, in_dim: int, hidden_dim: int = 1024, out_dim: int = 2048):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, out_dim)
        )

    def forward(self, x):
        return self.net(x)

class FullGatherLayer(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        output = [torch.zeros_like(x) for _ in range(dist.get_world_size())]
        dist.all_gather(output, x)
        return tuple(output)

    @staticmethod
    def backward(ctx, *grads):
        all_gradients = torch.stack(grads)
        dist.all_reduce(all_gradients)
        return all_gradients[dist.get_rank()]

