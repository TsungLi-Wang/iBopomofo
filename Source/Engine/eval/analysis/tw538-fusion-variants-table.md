# T2a fusion variants (N=10, λ=0.75, spoken LSTM, pool prep mean_ms≈63)

| variant | correct/537 |
|---------|-------------|
| baseline nu=0.25 | 348/537 |
| baseline nu=0.5 | 356/537 |
| baseline nu=0.75 | 349/537 |
| len_char nu=4 | 350/537 |
| len_char nu=8 | 347/537 |
| both_len_char nu=0.25 | 348/537 |
| both_len_char nu=0.5 | 357/537 |
| both_len_char nu=0.75 | 350/537 |
| both_len_char nu=1 | 337/537 |
| both_len_char nu=2 | 313/537 |
| both_len_char nu=4 | 296/537 |
| zscore alpha=0.75 | 351/537 |
| minmax alpha=0.75 | 350/537 |
| zscore alpha=1 | 349/537 |
| minmax alpha=1 | 350/537 |

**Best in this scan:** TABLE both_len_char nu=0.5 correct 357/537

Full raw: `tw538-fusion-variants.stdout.txt`

Note: length-norm LSTM-only never beats baseline 356; `both_len_char nu=0.5` reaches **357** (+1).
z-score/minmax peak at 351 — worse than baseline. Cheap fusion ceiling is thin; aligns with FUSION_LOSS only 28/114.
