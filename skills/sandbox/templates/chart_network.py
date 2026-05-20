import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(12, 8))

G = nx.Graph()

nodes = {nodes}
edges = {edges}

for node in nodes:
    G.add_node(node)

for edge in edges:
    if len(edge) >= 2:
        G.add_edge(edge[0], edge[1])

pos = nx.spring_layout(G, k=2, iterations=50)
nx.draw_networkx_nodes(G, pos, node_size=1500, node_color='#4A90D9', alpha=0.8, ax=ax)
nx.draw_networkx_labels(G, pos, font_size=10, font_family='SimHei', ax=ax)
nx.draw_networkx_edges(G, pos, width=1.5, alpha=0.5, edge_color='#666666', ax=ax)

ax.set_title('{title}', fontsize=16, fontweight='bold')
ax.axis('off')

plt.tight_layout()
plt.savefig('{output_path}', dpi=300, bbox_inches='tight')
plt.close()
