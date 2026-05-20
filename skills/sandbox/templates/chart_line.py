import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(10, 6))

x = {x_data}
y_series = {y_series}

for name, y in y_series.items():
    ax.plot(x, y, marker='o', linewidth=2, label=name)

ax.set_title('{title}', fontsize=16, fontweight='bold')
ax.set_xlabel('{xlabel}', fontsize=12)
ax.set_ylabel('{ylabel}', fontsize=12)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('{output_path}', dpi=300, bbox_inches='tight')
plt.close()
