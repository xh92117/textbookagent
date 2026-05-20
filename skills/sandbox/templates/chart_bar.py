import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(10, 6))

categories = {categories}
values = {values}
x = np.arange(len(categories))
width = 0.8 / len(values)

for i, (name, vals) in enumerate(values.items()):
    ax.bar(x + i * width, vals, width, label=name)

ax.set_title('{title}', fontsize=16, fontweight='bold')
ax.set_xlabel('{xlabel}', fontsize=12)
ax.set_ylabel('{ylabel}', fontsize=12)
ax.set_xticks(x + width * len(values) / 2)
ax.set_xticklabels(categories)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig('{output_path}', dpi=300, bbox_inches='tight')
plt.close()
