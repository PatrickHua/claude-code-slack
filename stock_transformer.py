"""
Minimal Transformer for Stock Price/Quantity Analysis
=====================================================
Generates synthetic stock data (price + volume), trains a small transformer
to predict the next time-step, and visualizes the full training process.
"""

import math
import numpy as np
import torch
import torch.nn as nn
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

torch.manual_seed(42)
np.random.seed(42)

# ── Synthetic stock data ─────────────────────────────────────────────────────
def generate_stock_data(n_days=2000):
    """Generate realistic-ish synthetic price + volume series."""
    t = np.arange(n_days, dtype=np.float32)
    # Price: trend + seasonality + noise (geometric-brownian-motion flavour)
    trend = 100 + 0.02 * t
    seasonal = 10 * np.sin(2 * np.pi * t / 252) + 5 * np.sin(2 * np.pi * t / 63)
    noise = np.cumsum(np.random.randn(n_days) * 0.5)
    price = trend + seasonal + noise

    # Volume: baseline with spikes correlated to price moves
    vol_base = 1e6 + 2e5 * np.sin(2 * np.pi * t / 21)
    vol_spike = 5e5 * np.abs(np.random.randn(n_days))
    volume = vol_base + vol_spike

    return price.astype(np.float32), volume.astype(np.float32)

# ── Dataset ──────────────────────────────────────────────────────────────────
class StockDataset(torch.utils.data.Dataset):
    def __init__(self, price, volume, seq_len=32):
        # Normalise each feature to [0,1]
        self.seq_len = seq_len
        self.price = (price - price.min()) / (price.max() - price.min() + 1e-8)
        self.volume = (volume - volume.min()) / (volume.max() - volume.min() + 1e-8)
        # Stack into (N, 2) then create sliding windows
        data = np.stack([self.price, self.volume], axis=-1)  # (N, 2)
        self.data = torch.tensor(data, dtype=torch.float32)

    def __len__(self):
        return len(self.data) - self.seq_len

    def __getitem__(self, idx):
        x = self.data[idx : idx + self.seq_len]        # (seq_len, 2)
        y = self.data[idx + 1 : idx + self.seq_len + 1] # next-step targets
        return x, y

# ── Positional encoding ─────────────────────────────────────────────────────
class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=512):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]

# ── Transformer model ───────────────────────────────────────────────────────
class StockTransformer(nn.Module):
    def __init__(self, n_features=2, d_model=64, nhead=4, n_layers=2, dim_ff=128, dropout=0.1):
        super().__init__()
        self.input_proj = nn.Linear(n_features, d_model)
        self.pos_enc = PositionalEncoding(d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_ff,
            dropout=dropout, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.output_proj = nn.Linear(d_model, n_features)

    def forward(self, x):
        # x: (batch, seq_len, 2)
        mask = nn.Transformer.generate_square_subsequent_mask(x.size(1), device=x.device)
        h = self.input_proj(x)
        h = self.pos_enc(h)
        h = self.transformer(h, mask=mask)
        return self.output_proj(h)

# ── Training ─────────────────────────────────────────────────────────────────
def train():
    price, volume = generate_stock_data(2000)

    seq_len = 32
    split = 1600
    train_ds = StockDataset(price[:split], volume[:split], seq_len)
    val_ds = StockDataset(price[split:], volume[split:], seq_len)
    train_dl = torch.utils.data.DataLoader(train_ds, batch_size=64, shuffle=True)
    val_dl = torch.utils.data.DataLoader(val_ds, batch_size=64)

    model = StockTransformer()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=60)
    criterion = nn.MSELoss()

    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {n_params:,}")
    print(f"Train samples: {len(train_ds)}, Val samples: {len(val_ds)}")
    print(f"Training for 60 epochs...\n")

    epochs = 60
    history = {"train_loss": [], "val_loss": [], "lr": [],
               "train_price_loss": [], "train_vol_loss": [],
               "val_price_loss": [], "val_vol_loss": []}

    for epoch in range(1, epochs + 1):
        # ── Train ──
        model.train()
        t_loss, t_ploss, t_vloss, n = 0, 0, 0, 0
        for xb, yb in train_dl:
            pred = model(xb)
            loss = criterion(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            bs = xb.size(0)
            t_loss += loss.item() * bs
            t_ploss += ((pred[:,:,0] - yb[:,:,0])**2).mean().item() * bs
            t_vloss += ((pred[:,:,1] - yb[:,:,1])**2).mean().item() * bs
            n += bs
        t_loss /= n; t_ploss /= n; t_vloss /= n

        # ── Validate ──
        model.eval()
        v_loss, v_ploss, v_vloss, n = 0, 0, 0, 0
        with torch.no_grad():
            for xb, yb in val_dl:
                pred = model(xb)
                loss = criterion(pred, yb)
                bs = xb.size(0)
                v_loss += loss.item() * bs
                v_ploss += ((pred[:,:,0] - yb[:,:,0])**2).mean().item() * bs
                v_vloss += ((pred[:,:,1] - yb[:,:,1])**2).mean().item() * bs
                n += bs
        v_loss /= n; v_ploss /= n; v_vloss /= n

        lr = optimizer.param_groups[0]["lr"]
        scheduler.step()

        history["train_loss"].append(t_loss)
        history["val_loss"].append(v_loss)
        history["lr"].append(lr)
        history["train_price_loss"].append(t_ploss)
        history["train_vol_loss"].append(t_vloss)
        history["val_price_loss"].append(v_ploss)
        history["val_vol_loss"].append(v_vloss)

        if epoch % 10 == 0 or epoch == 1:
            print(f"Epoch {epoch:3d} | train {t_loss:.6f} | val {v_loss:.6f} | lr {lr:.2e}")

    # ── Generate predictions on validation set ───────────────────────────
    model.eval()
    with torch.no_grad():
        # Use last seq_len window and autoregressively predict
        val_norm_price = (price[split:] - price[:split].min()) / (price[:split].max() - price[:split].min() + 1e-8)
        val_norm_vol = (volume[split:] - volume[:split].min()) / (volume[:split].max() - volume[:split].min() + 1e-8)
        val_data = torch.tensor(np.stack([val_norm_price, val_norm_vol], -1), dtype=torch.float32)

        preds = []
        for i in range(len(val_data) - seq_len):
            inp = val_data[i:i+seq_len].unsqueeze(0)
            out = model(inp)
            preds.append(out[0, -1].numpy())  # last step prediction
        preds = np.array(preds)

    # ── Visualisation ────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 14))
    fig.suptitle("Stock Transformer — Training & Prediction Dashboard", fontsize=15, fontweight="bold", y=0.98)
    gs = GridSpec(3, 2, hspace=0.35, wspace=0.28, top=0.93, bottom=0.06)
    epochs_x = range(1, epochs + 1)

    # 1) Overall loss curves
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(epochs_x, history["train_loss"], "royalblue", lw=2, label="Train")
    ax1.plot(epochs_x, history["val_loss"], "tomato", lw=2, label="Val")
    ax1.set_xlabel("Epoch"); ax1.set_ylabel("MSE Loss")
    ax1.set_title("Total Loss"); ax1.legend(); ax1.grid(alpha=0.3)

    # 2) Per-feature loss
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(epochs_x, history["train_price_loss"], "royalblue", lw=1.5, label="Train Price")
    ax2.plot(epochs_x, history["val_price_loss"], "tomato", lw=1.5, label="Val Price")
    ax2.plot(epochs_x, history["train_vol_loss"], "royalblue", lw=1.5, ls="--", label="Train Volume")
    ax2.plot(epochs_x, history["val_vol_loss"], "tomato", lw=1.5, ls="--", label="Val Volume")
    ax2.set_xlabel("Epoch"); ax2.set_ylabel("MSE Loss")
    ax2.set_title("Per-Feature Loss"); ax2.legend(fontsize=8); ax2.grid(alpha=0.3)

    # 3) Learning rate schedule
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(epochs_x, history["lr"], "seagreen", lw=2)
    ax3.set_xlabel("Epoch"); ax3.set_ylabel("Learning Rate")
    ax3.set_title("Cosine Annealing LR Schedule"); ax3.grid(alpha=0.3)

    # 4) Predicted vs actual price (validation)
    ax4 = fig.add_subplot(gs[1, 1])
    actual_p = val_norm_price[seq_len:]
    pred_p = preds[:, 0]
    t_val = np.arange(len(actual_p))
    ax4.plot(t_val, actual_p, "royalblue", lw=1.2, label="Actual Price", alpha=0.8)
    ax4.plot(t_val, pred_p, "tomato", lw=1.2, label="Predicted Price", alpha=0.8)
    ax4.set_xlabel("Day (validation set)"); ax4.set_ylabel("Normalised Price")
    ax4.set_title("Price: Predicted vs Actual"); ax4.legend(); ax4.grid(alpha=0.3)

    # 5) Predicted vs actual volume (validation)
    ax5 = fig.add_subplot(gs[2, 0])
    actual_v = val_norm_vol[seq_len:]
    pred_v = preds[:, 1]
    ax5.plot(t_val, actual_v, "royalblue", lw=1.2, label="Actual Volume", alpha=0.8)
    ax5.plot(t_val, pred_v, "tomato", lw=1.2, label="Predicted Volume", alpha=0.8)
    ax5.set_xlabel("Day (validation set)"); ax5.set_ylabel("Normalised Volume")
    ax5.set_title("Volume: Predicted vs Actual"); ax5.legend(); ax5.grid(alpha=0.3)

    # 6) Prediction error distribution
    ax6 = fig.add_subplot(gs[2, 1])
    price_err = pred_p - actual_p
    vol_err = pred_v - actual_v
    ax6.hist(price_err, bins=40, alpha=0.6, color="royalblue", label=f"Price (std={price_err.std():.4f})")
    ax6.hist(vol_err, bins=40, alpha=0.6, color="tomato", label=f"Volume (std={vol_err.std():.4f})")
    ax6.set_xlabel("Prediction Error"); ax6.set_ylabel("Count")
    ax6.set_title("Error Distribution"); ax6.legend(); ax6.grid(alpha=0.3)

    out_path = "/home/patrick/claude-code-slack/stock_transformer_results.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nDashboard saved to {out_path}")

if __name__ == "__main__":
    train()
