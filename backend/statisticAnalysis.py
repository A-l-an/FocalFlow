import json
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import os
from matplotlib import font_manager
import platform
import argparse
from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter
from datetime import datetime
import matplotlib.patches as patches

parser = argparse.ArgumentParser(description='分析UI交互数据并生成可视化图表')
parser.add_argument('--with-bg', action='store_true', help='使用手机截图作为背景')
parser.add_argument('--json-file', type=str, default="ui_interaction_log_User_12_Task_2_4_0617110805.json", help='要分析的JSON文件路径')
parser.add_argument('--screenshot-dir', type=str, default="screenshot", help='截图目录路径')
parser.add_argument('--generate-video', action='store_true', help='生成交互路径的动画视频')
parser.add_argument('--video-duration', type=int, default=60, help='视频总时长（秒）')
parser.add_argument('--fps', type=int, default=3, help='视频帧率')
args = parser.parse_args()

system = platform.system()
if system == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'Heiti TC', 'Hiragino Sans GB', 'STHeiti']
elif system == 'Windows':
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimSun', 'SimHei']
else:
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'WenQuanYi Micro Hei', 'Droid Sans Fallback']

plt.rcParams['axes.unicode_minus'] = False

fonts = [f.name for f in font_manager.fontManager.ttflist]
chinese_fonts = [f for f in fonts if any(x in f for x in ['Hei', 'Yuan', 'Ming', 'Song', 'Kai', 'Fang', 'Sans', 'Gothic', 'Mincho', 'Simsun', 'YaHei', 'PingFang', 'Hiragino'])]

os.makedirs("user_data/dataAnalysis", exist_ok=True)

def detect_and_normalize_format(data):
    """检测JSON格式并返回标准化的数据结构"""
    is_new_format = "sessionInfo" in data and "interactions" in data
    
    if is_new_format:
        print("检测到新格式的JSON数据")
        session_info = data.get("sessionInfo", {})
        user_id = session_info.get("userId", "unknown")
        task_id = session_info.get("taskId", "unknown") 
        start_time = session_info.get("startTime", "unknown")
        
        print(f"会话信息 - 用户ID: {user_id}, 任务ID: {task_id}, 开始时间: {start_time}")
        
        total_interactions = data.get("totalInteractionCount", 0)
        last_update = data.get("lastUpdateTime", "unknown")
        print(f"总交互次数: {total_interactions}, 最后更新时间: {last_update}")
        
        return {
            "format_version": "new",
            "session_info": session_info,
            "windows_data": data.get("interactions", {}),
            "metadata": {
                "totalInteractionCount": total_interactions,
                "lastUpdateTime": last_update,
                "timestamp": data.get("timestamp", "unknown")
            }
        }
    else:
        print("检测到旧格式的JSON数据")
        user_id = data.get("userId", "unknown")
        task_id = data.get("taskId", "unknown")
        timestamp = data.get("timestamp", "unknown")
        
        print(f"会话信息 - 用户ID: {user_id}, 任务ID: {task_id}, 时间戳: {timestamp}")
        
        return {
            "format_version": "old", 
            "session_info": {
                "userId": user_id,
                "taskId": task_id,
                "timestamp": timestamp
            },
            "windows_data": data.get("windows", {}),
            "metadata": {}
        }

def get_time_spent(step):
    """兼容获取时间消耗，支持新旧格式"""
    time_value = step.get("timeSpentOnPrevious", step.get("timeSpent", 0))
    if isinstance(time_value, (int, float)):
        return time_value
    return 0

def get_windows_data(normalized_data):
    """获取标准化的窗口数据"""
    windows_data = normalized_data["windows_data"]
    format_version = normalized_data["format_version"]
    
    if format_version == "new":
        for win_id, win_data in windows_data.items():
            if "windowName" in win_data:
                window_name = win_data.get("windowName", "unknown")
                print(f"窗口 {win_id} 名称: {window_name}")
    
    return windows_data

with open(args.json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

normalized_data = detect_and_normalize_format(data)
windows = get_windows_data(normalized_data)

all_paths = []

ui_total_times = {}
element_revisit_counts = {}

def get_element_label(element):
    return (
        element.get("text") or
        element.get("contentDescription") or
        element.get("childName") or
        element.get("name") or
        "Unknown"
    )

def build_global_timeline(windows):
    """构建全局时间线，按时间顺序排列所有交互事件"""
    timeline = []
    
    for win_id, win_data in windows.items():
        elements = win_data.get("elements", {})
        
        label_map = {}
        position_map = {}
        for eid, e in elements.items():
            label = get_element_label(e)
            label_map[eid] = label
            if "position" in e:
                position_map[eid] = (e["position"]["x"], e["position"]["y"])
        
        for eid, e in elements.items():
            for record in e.get("visitRecords", []):
                start_time_str = record.get("startTime", "")
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        
                        for step in record.get("navigationPath", []):
                            curr = step.get("currentElement")
                            prev = step.get("previousElement", None)
                            time_spent = get_time_spent(step)
                            
                            curr_label = label_map.get(curr, curr)
                            
                            timeline.append({
                                'timestamp': start_time,
                                'action': 'add_node',
                                'element': curr_label,
                                'element_id': curr,
                                'ui_window': win_id,
                                'position': position_map.get(curr),
                                'time_spent': time_spent
                            })
                            
                            if prev and prev != "null":
                                prev_label = label_map.get(prev, prev)
                                timeline.append({
                                    'timestamp': start_time,
                                    'action': 'add_edge',
                                    'from_element': prev_label,
                                    'to_element': curr_label,
                                    'ui_window': win_id,
                                    'weight': time_spent
                                })
                    except Exception as e:
                        print(f"解析时间失败: {start_time_str}, 错误: {e}")
    
    timeline.sort(key=lambda x: x['timestamp'])
    return timeline

def draw_ui_graph(G, ui_id, pos):
    """为单个UI界面绘制并保存图形"""
    screen_width = 1080
    screen_height = 2400
    
    fig = plt.figure(figsize=(screen_width/100, screen_height/100), dpi=100)
    ax = fig.add_subplot(111)
    
    background_loaded = draw_ui_background(ax, ui_id, screen_width, screen_height)
    draw_ui_elements(ax, G, pos, screen_width, screen_height, background_loaded)
    
    plt.title(f"UI {ui_id} 用户浏览路径图")
    plt.xlim(0, screen_width)
    plt.ylim(0, screen_height)
    plt.axis('off')
    
    plt.savefig(f"user_data/dataAnalysis/ui_{ui_id}_path.png", bbox_inches='tight', dpi=100)
    plt.close()

def draw_ui_background(ax, ui_id, screen_width, screen_height):
    """绘制UI背景图，返回是否成功加载背景"""
    background_loaded = False
    if args.with_bg:
        screenshot_paths = [
            f"{args.screenshot_dir}/ui_{ui_id}.jpg",
            f"{args.screenshot_dir}/screenshot_{ui_id}.jpg",
            f"{args.screenshot_dir}/screenshot_0.jpg"
        ]
        
        for path in screenshot_paths:
            if os.path.exists(path):
                try:
                    img = plt.imread(path)
                    img_height, img_width = img.shape[:2]
                    
                    aspect_ratio = img_width / img_height
                    screen_aspect_ratio = screen_width / screen_height
                    
                    if aspect_ratio > screen_aspect_ratio:
                        adjusted_height = screen_width / aspect_ratio
                        y_offset = (screen_height - adjusted_height) / 2
                        ax.imshow(img, extent=[0, screen_width, y_offset, y_offset + adjusted_height], 
                                 aspect='auto', alpha=0.4)
                    else:
                        adjusted_width = screen_height * aspect_ratio
                        x_offset = (screen_width - adjusted_width) / 2
                        ax.imshow(img, extent=[x_offset, x_offset + adjusted_width, 0, screen_height], 
                                 aspect='auto', alpha=0.4)
                    
                    print(f"使用截图 {path} 作为UI {ui_id}的背景")
                    background_loaded = True
                    break
                except Exception as e:
                    print(f"加载截图 {path} 失败: {e}")
        
        if not background_loaded:
            print(f"未找到UI {ui_id}的有效截图")
    
    return background_loaded

def draw_ui_elements(ax, G, pos, screen_width, screen_height, background_loaded, 
                    current_nodes=None, current_edges=None, highlight_node=None):
    """绘制UI元素（节点和边）"""
    if current_nodes is None:
        current_nodes = list(G.nodes())
    if current_edges is None:
        current_edges = list(G.edges())
    
    # 仅在绘图层面隐藏以 android/com 开头的节点（大小写不敏感），以及连接到这些节点的边
    def _is_hidden_label(label):
        if isinstance(label, str):
            stripped = label.strip().lower()
            return stripped.startswith('android') or stripped.startswith('com') or stripped.startswith('pop')
        return False

    visible_nodes = [n for n in current_nodes if not _is_hidden_label(n)]
    visible_node_set = set(visible_nodes)
    visible_edges = [e for e in current_edges if e[0] in visible_node_set and e[1] in visible_node_set]

    if highlight_node is not None and highlight_node not in visible_node_set:
        highlight_node = None

    current_G = G.subgraph(visible_nodes).copy()
    current_G.add_edges_from([edge for edge in visible_edges if edge[0] in visible_nodes and edge[1] in visible_nodes])
    
    if len(current_G.nodes()) == 0:
        return
    
    edge_weights = []
    edge_labels = {}
    for u, v in current_G.edges():
        if G.has_edge(u, v):
            weight = G[u][v]['weight']
            edge_weights.append(max(min(weight/1000, 5), 1.5))
            edge_labels[(u, v)] = weight
        else:
            edge_weights.append(1.5)
    
    node_labels = {}
    for n in current_G.nodes():
        if isinstance(n, str):
            if len(n) > 20:
                node_labels[n] = n[:17] + "..."
            else:
                node_labels[n] = n
    
    node_size = 400 if background_loaded else 600
    node_alpha = 0.6 if background_loaded else 0.8
    
    node_colors = []
    for node in current_G.nodes():
        if node == highlight_node:
            node_colors.append('red')
        else:
            node_colors.append('lightblue')
    
    current_pos = {node: pos[node] for node in current_G.nodes() if node in pos}
    
    if len(current_G.edges()) > 0:
        nx.draw(current_G, current_pos, ax=ax, with_labels=False, node_size=node_size, 
                node_color=node_colors, font_size=25, font_weight='bold', edge_color='gray', 
                width=edge_weights, alpha=node_alpha,
                arrows=True, arrowsize=12, arrowstyle='-|>', connectionstyle='arc3,rad=0.1')
    else:
        nx.draw_networkx_nodes(current_G, current_pos, ax=ax, node_size=node_size,
                              node_color=node_colors, alpha=node_alpha)
    
    # 为每个节点单独绘制标签，支持不同的位置和颜色
    for node in current_G.nodes():
        if node in node_labels:
            if node == "Please enter merchant or product name":
                # 将"美食"节点的标签位置调整到节点下方，颜色设为蓝色
                x, y = current_pos[node]
                label_pos = (x, y - 50)  # 向下偏移50像素
                ax.text(label_pos[0], label_pos[1], node_labels[node], 
                       fontsize=25, fontweight='bold', color='black',
                       ha='center', va='center')
            else:
                # 其他节点使用默认位置和颜色
                x, y = current_pos[node]
                label_pos = (x, y - 50)  # 向下偏移50像素
                ax.text(label_pos[0], label_pos[1], node_labels[node], 
                       fontsize=25, fontweight='bold', color='blue',
                       ha='center', va='center')

def animate_frame(frame_num, G, pos, timeline, ax, background_loaded, screen_width, screen_height, ui_id):
    """动画帧回调函数"""
    ax.clear()
    
    if background_loaded:
        draw_ui_background(ax, ui_id, screen_width, screen_height)
    
    current_nodes = set()
    current_edges = []
    highlight_node = None

    # 与绘图阶段一致的隐藏规则（仅用于可视化，不改动数据）
    def _is_hidden_label(label):
        if isinstance(label, str):
            stripped = label.strip().lower()
            return stripped.startswith('android') or stripped.startswith('com') or stripped.startswith('pop')
        return False

    # 累积到当前帧为止的可见节点时间顺序序列
    visible_sequence = []
    
    if frame_num < len(timeline):
        for i in range(frame_num + 1):
            event = timeline[i]
            if event['action'] == 'add_node':
                label = event['element']
                if not _is_hidden_label(label):
                    current_nodes.add(label)
                    if len(visible_sequence) == 0 or visible_sequence[-1] != label:
                        visible_sequence.append(label)
                    if i == frame_num:
                        highlight_node = label
                else:
                    if i == frame_num:
                        highlight_node = None
            # 忽略原始 add_edge 的直接使用，改为在可见节点序列上补边
        # 根据可见节点序列补边，跨越被隐藏节点
        for j in range(1, len(visible_sequence)):
            u = visible_sequence[j-1]
            v = visible_sequence[j]
            edge = (u, v)
            if edge not in current_edges:
                current_edges.append(edge)
    
    draw_ui_elements(ax, G, pos, screen_width, screen_height, background_loaded,
                    current_nodes=list(current_nodes), current_edges=current_edges, 
                    highlight_node=highlight_node)
    
    if frame_num < len(timeline):
        pass
    
    ax.set_xlim(0, screen_width)
    ax.set_ylim(0, screen_height)
    ax.axis('off')

def create_animation_for_ui(ui_name, G, pos, timeline, background_loaded):
    """为UI创建动画"""
    if len(timeline) == 0:
        print(f"UI {ui_name} 没有时间线数据，跳过动画生成")
        return None
    
    screen_width = 1080
    screen_height = 2400
    
    fig = plt.figure(figsize=(screen_width/100, screen_height/100), dpi=100)
    ax = fig.add_subplot(111)
    
    total_frames = len(timeline)
    interval = (args.video_duration * 1000) // total_frames
    
    print(f"为UI {ui_name} 创建动画，共 {total_frames} 帧，间隔 {interval}ms")
    
    anim = FuncAnimation(fig, animate_frame, frames=total_frames,
                        fargs=(G, pos, timeline, ax, background_loaded, screen_width, screen_height, ui_name),
                        interval=interval, repeat=False, blit=False)
    
    return anim, fig

def save_animation_video(animation, ui_name, fps=10):
    """保存动画为视频文件"""
    try:
        try:
            writer = FFMpegWriter(fps=fps, metadata=dict(artist='UI Analysis'), bitrate=1800)
            video_path = f"user_data/dataAnalysis/ui_{ui_name}_animation.mp4"
            animation.save(video_path, writer=writer)
            print(f"视频已保存: {video_path}")
            return True
        except Exception as e:
            print(f"保存MP4失败: {e}，尝试保存为GIF...")
            try:
                writer = PillowWriter(fps=fps)
                gif_path = f"user_data/dataAnalysis/ui_{ui_name}_animation.gif"
                animation.save(gif_path, writer=writer)
                print(f"GIF已保存: {gif_path}")
                return True
            except Exception as gif_error:
                print(f"保存GIF也失败: {gif_error}")
                print("提示：您可能需要安装 ffmpeg 或 pillow 来支持视频/GIF生成")
                return False
    except Exception as e:
        print(f"保存动画失败: {e}")
        return False


for win_id, win_data in windows.items():
    ui_name = win_id
    total_time = 0
    path = []
    last_label = None
    
    G = nx.DiGraph()

    elements = win_data.get("elements", {})
    label_map = {}
    position_map = {}

    for eid, e in elements.items():
        label = get_element_label(e)
        label_map[eid] = label
        if "position" in e:
            position_map[eid] = (e["position"]["x"], e["position"]["y"])

    revisit_count = {}
    last_visited_label = None
    is_first_interaction = True
    for eid, e in elements.items():
        for record in e.get("visitRecords", []):
            for step in record.get("navigationPath", []):
                curr = step.get("currentElement")
                prev = step.get("previousElement", None)
                time = get_time_spent(step)
                
                if isinstance(time, (int, float)):
                    total_time += time
                
                curr_label = label_map.get(curr, curr)
                if curr_label != last_visited_label:
                    if curr_label not in revisit_count:
                        revisit_count[curr_label] = 1
                    else:
                        revisit_count[curr_label] += 1
                last_visited_label = curr_label
                
                if not G.has_node(curr_label):
                    G.add_node(curr_label)
                
                if curr in position_map:
                    G.nodes[curr_label]['pos'] = position_map[curr]
                
                if curr_label != last_label:
                    path.append(curr_label)
                    last_label = curr_label
                
                if prev and not is_first_interaction:
                    prev_label = label_map.get(prev, prev)
                    if not G.has_node(prev_label):
                        G.add_node(prev_label)
                    
                    if prev_label != curr_label:
                        if G.has_edge(prev_label, curr_label):
                            G[prev_label][curr_label]['weight'] += time
                        else:
                            G.add_edge(prev_label, curr_label, weight=time)
                
                if is_first_interaction:
                    is_first_interaction = False

    ui_total_times[ui_name] = total_time
    all_paths.append((ui_name, path))
    element_revisit_counts[ui_name] = revisit_count

    pos = {}
    
    screen_width = 1080
    screen_height = 2400
    
    nodes_with_pos = 0
    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')
    
    position_data = {}
    for node in G.nodes():
        if 'pos' in G.nodes[node]:
            orig_x, orig_y = G.nodes[node]['pos']
            
            orig_x = min(max(orig_x, 0), screen_width)
            orig_y = min(max(orig_y, 0), screen_height)
            
            position_data[node] = (orig_x, orig_y)
            
            min_x = min(min_x, orig_x)
            max_x = max(max_x, orig_x)
            min_y = min(min_y, orig_y)
            max_y = max(max_y, orig_y)
            
            nodes_with_pos += 1
    
    if max_x - min_x < 50:
        max_x = min_x + 200
    if max_y - min_y < 50:
        max_y = min_y + 200
    
    for node, (x, y) in position_data.items():
        pos[node] = (x, screen_height - y)
    
    print(f"UI {ui_name} 共有 {len(G.nodes())} 个节点，其中 {nodes_with_pos} 个有位置信息")
    if nodes_with_pos > 0:
        print(f"位置范围: X({min_x:.0f}-{max_x:.0f}), Y({min_y:.0f}-{max_y:.0f})")

    if len(pos) < len(G.nodes()):
        missing_pos_nodes = [node for node in G.nodes() if node not in pos]
        print(f"没有位置信息的节点: {len(missing_pos_nodes)}个")
        
        if len(pos) == 0:
            pos = nx.spring_layout(G, seed=42, scale=screen_width*0.7, center=(screen_width/2, screen_height/2))
        else:
            fixed_nodes = list(pos.keys())
            fixed_positions = {node: pos[node] for node in fixed_nodes}
            
            center_x = min_x + (max_x - min_x) / 2
            center_y = screen_height - (min_y + (max_y - min_y) / 2)
            scale = min(screen_width, screen_height) * 0.3
            
            temp_pos = nx.spring_layout(G, pos=fixed_positions, fixed=fixed_nodes, seed=42,
                                       scale=scale, center=(center_x, center_y))
            
            pos.update(temp_pos)
    
    draw_ui_graph(G, ui_name, pos)
    
    if args.generate_video:
        # 仅为 window_1330 生成动画视频
        if ui_name != "window_1330":
            print(f"\n跳过为UI {ui_name} 生成动画视频（仅生成 window_1330")
            continue
        print(f"\n开始为UI {ui_name} 生成动画视频...")
        
        ui_windows = {ui_name: win_data}
        ui_timeline = build_global_timeline(ui_windows)
        
        ui_timeline = [event for event in ui_timeline if event['ui_window'] == ui_name]
        
        if len(ui_timeline) > 0:
            background_loaded = False
            if args.with_bg:
                screenshot_paths = [
                    f"{args.screenshot_dir}/ui_{ui_name}.jpg",
                    f"{args.screenshot_dir}/screenshot_{ui_name}.jpg",
                    f"{args.screenshot_dir}/screenshot_0.jpg"
                ]
                for path in screenshot_paths:
                    if os.path.exists(path):
                        background_loaded = True
                        break
            
            anim_result = create_animation_for_ui(ui_name, G, pos, ui_timeline, background_loaded)
            
            if anim_result is not None:
                anim, fig = anim_result
                save_animation_video(anim, ui_name, fps=args.fps)
                plt.close(fig)
            else:
                print(f"UI {ui_name} 动画创建失败")
        else:
            print(f"UI {ui_name} 没有有效的时间线数据，跳过动画生成")

for ui_name, path in all_paths:
    print(f"\nUI: {ui_name}")
    print("访问路径:", " -> ".join(path))
    print("总停留时间:", ui_total_times[ui_name]/1000, "s")
    print("元素重访次数：")
    for label, count in element_revisit_counts[ui_name].items():
        print(f"  {label}: {count} 次")
if args.generate_video:
    print("\n" + "="*50)
    print("视频生成完成！")
    print("生成的文件位于: user_data/dataAnalysis/")
    print("\n使用说明：")
    print("- 动画显示了用户交互的时间顺序")
    print("- 红色高亮的节点表示当前活跃的UI元素")
    print("- 左上角显示当前时间戳和进度")
    print("- 如果启用了背景图(--with-bg)，将显示手机截图作为背景")
    
    if len(windows) > 1:
        print("\n考虑生成全局交互概览...")
        global_timeline = build_global_timeline(windows)
        if len(global_timeline) > 0:
            print(f"全局时间线包含 {len(global_timeline)} 个交互事件")
            print(f"时间跨度: {global_timeline[0]['timestamp'].strftime('%H:%M:%S')} - {global_timeline[-1]['timestamp'].strftime('%H:%M:%S')}")
        else:
            print("全局时间线为空，无法生成概览视频")
    
    print("="*50)
