import os
from typing import Optional
from .executor import SandboxExecutor, SandboxResult


class ChartGenerator:
    def __init__(self, executor: SandboxExecutor = None):
        self.executor = executor or SandboxExecutor()

    def _savefig_path(self, filename: str) -> str:
        return os.path.join(self.executor.output_dir, filename).replace('\\', '/')

    def _generate_chart(self, chart_code: str, filename: str) -> SandboxResult:
        save_path = self._savefig_path(filename)
        font_setup = self._build_font_setup_code()
        full_code = f"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
{font_setup}
{chart_code}
plt.savefig('{save_path}', dpi=150, bbox_inches='tight')
plt.close()
"""
        return self.executor.execute(full_code)

    def _build_font_setup_code(self) -> str:
        import matplotlib.font_manager as fm
        import os as _os
        candidates = ['SimHei', 'Microsoft YaHei', 'STSong', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Arial Unicode MS']
        available = set(f.name for f in fm.fontManager.ttflist)
        chosen = next((f for f in candidates if f in available), None)
        if chosen:
            return f"plt.rcParams['font.sans-serif'] = ['{chosen}'] + plt.rcParams['font.sans-serif']\nplt.rcParams['axes.unicode_minus'] = False"
        font_dirs = ['C:/Windows/Fonts', _os.path.expanduser('~/Library/Fonts'), '/usr/share/fonts/truetype']
        for fd in font_dirs:
            if _os.path.isdir(fd):
                for fn in _os.listdir(fd):
                    fl = fn.lower()
                    if any(k in fl for k in ['simhei', 'msyh', 'stsong', 'wenquanyi', 'noto']):
                        fp = _os.path.join(fd, fn)
                        fm.fontManager.addfont(fp)
                        prop = fm.FontProperties(fname=fp)
                        name = prop.get_name()
                        return f"fm.fontManager.addfont('{fp.replace(_os.sep, '/')}')\nplt.rcParams['font.sans-serif'] = ['{name}'] + plt.rcParams['font.sans-serif']\nplt.rcParams['axes.unicode_minus'] = False"
        return ""

    def generate_line_chart(self, x_data: str, y_data: str, title: str = "", xlabel: str = "", ylabel: str = "", filename: str = "line_chart.png") -> SandboxResult:
        code = f"""
x = {x_data}
y = {y_data}
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(x, y, marker='o', linewidth=2, markersize=6)
ax.set_title('{title}')
ax.set_xlabel('{xlabel}')
ax.set_ylabel('{ylabel}')
ax.grid(True, alpha=0.3)
"""
        return self._generate_chart(code, filename)

    def generate_bar_chart(self, categories: str, values: str, title: str = "", xlabel: str = "", ylabel: str = "", filename: str = "bar_chart.png") -> SandboxResult:
        code = f"""
categories = {categories}
values = {values}
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(categories, values, color='#2563EB', alpha=0.8)
ax.set_title('{title}')
ax.set_xlabel('{xlabel}')
ax.set_ylabel('{ylabel}')
"""
        return self._generate_chart(code, filename)

    def generate_pie_chart(self, labels: str, sizes: str, title: str = "", filename: str = "pie_chart.png") -> SandboxResult:
        code = f"""
labels = {labels}
sizes = {sizes}
fig, ax = plt.subplots(figsize=(7, 7))
ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
ax.set_title('{title}')
"""
        return self._generate_chart(code, filename)

    def generate_scatter_chart(self, x_data: str, y_data: str, title: str = "", xlabel: str = "", ylabel: str = "", filename: str = "scatter_chart.png") -> SandboxResult:
        code = f"""
x = {x_data}
y = {y_data}
fig, ax = plt.subplots(figsize=(8, 5))
ax.scatter(x, y, c='#2563EB', alpha=0.6, s=50)
ax.set_title('{title}')
ax.set_xlabel('{xlabel}')
ax.set_ylabel('{ylabel}')
ax.grid(True, alpha=0.3)
"""
        return self._generate_chart(code, filename)

    def generate_network_graph(self, nodes_code: str, edges_code: str, title: str = "", filename: str = "network.png") -> SandboxResult:
        font_setup = self._build_font_setup_code()
        code = f"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import networkx as nx
{font_setup}

G = nx.Graph()
{nodes_code}
{edges_code}

fig, ax = plt.subplots(figsize=(10, 8))
pos = nx.spring_layout(G, seed=42)
_font_family = plt.rcParams['font.sans-serif'][0] if plt.rcParams['font.sans-serif'] else 'sans-serif'
nx.draw(G, pos, with_labels=True, node_color='#2563EB', node_size=1500, font_size=10, font_family=_font_family, ax=ax)
ax.set_title('{title}')
"""
        save_path = self._savefig_path(filename)
        full_code = f"""
{code}
plt.savefig('{save_path}', dpi=150, bbox_inches='tight')
plt.close()
"""
        return self.executor.execute(full_code)

    def execute_custom_code(self, code: str, filename: str = "custom_chart.png") -> SandboxResult:
        return self._generate_chart(code, filename)
