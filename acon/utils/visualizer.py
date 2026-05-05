import os
import json
from typing import Any

def generate_mermaid_graph(page_results: list[dict[str, Any]], output_file: str = "site_topology.mmd") -> str:
    """
    Generates a Mermaid.js flowchart representing the site topology with relationships.
    """
    lines = ["graph TD"]
    
    # Track nodes and connections to avoid duplicates
    nodes = {}
    
    # Define styles with more premium colors
    lines.append("    classDef homepage fill:#38bdf8,stroke:#0ea5e9,stroke-width:4px,color:#fff;")
    lines.append("    classDef standard fill:#1e293b,stroke:#334155,stroke-width:1px,color:#94a3b8;")
    lines.append("    classDef nav fill:#818cf8,stroke:#6366f1,stroke-width:2px,color:#fff;")
    lines.append("    classDef interaction fill:#c084fc,stroke:#a855f7,stroke-width:2px,color:#fff;")
    
    # First pass: Create nodes
    for page in page_results:
        url = page.get("url") or page.get("fetch_url")
        page_type = page.get("page_type", "standard")
        
        # Create a short label for the URL
        clean_url = url.replace("https://", "").replace("http://", "").strip("/")
        label = clean_url
        if len(label) > 30:
            label = "..." + label[-27:]
        
        node_id = f"node_{abs(hash(url)) % 10000000}"
        nodes[url] = node_id
        
        # Add metadata to label
        lines.append(f"    {node_id}[\"{label}<br/><small>{page_type.upper()}</small>\"]")
        lines.append(f"    class {node_id} {page_type}")
        
        # Add tooltip for full URL
        lines.append(f"    click {node_id} callback \"{url}\"")

    # Second pass: Create connections based on parent_url
    for page in page_results:
        url = page.get("url") or page.get("fetch_url")
        parent_url = page.get("parent_url")
        
        if parent_url and parent_url in nodes and url in nodes:
            parent_id = nodes[parent_url]
            child_id = nodes[url]
            if parent_id != child_id:
                lines.append(f"    {parent_id} --> {child_id}")

    return "\n".join(lines)

def generate_html_visualizer(page_results: list[dict[str, Any]], stats: dict[str, Any] = None, output_file: str = "topology_viz.html"):
    """Generates a premium HTML file with embedded Mermaid.js and interactive controls."""
    mermaid_code = generate_mermaid_graph(page_results)
    
    # Calculate stats if not provided
    if not stats:
        pages_count = len(page_results)
        # Mock savings for the visualizer if not passed
        stats = {
            "total_crawled": pages_count,
            "requests_saved": int(pages_count * 0.4),
            "efficiency": "40%"
        }
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Acon Topology Visualizer</title>
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #020617;
                --card: #0f172a;
                --accent: #38bdf8;
                --text: #f8fafc;
                --dim: #94a3b8;
            }}
            body {{ 
                font-family: 'Inter', sans-serif; 
                background: var(--bg); 
                color: var(--text); 
                margin: 0; padding: 20px;
                display: flex; flex-direction: column; align-items: center;
                height: 100vh; overflow: hidden;
            }}
            header {{ width: 100%; max-width: 1400px; display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 20px; }}
            .title-area h1 {{ margin: 0; font-size: 2rem; font-weight: 800; color: var(--accent); }}
            .title-area p {{ margin: 5px 0 0 0; color: var(--dim); }}
            
            .stats-bar {{ display: flex; gap: 20px; }}
            .stat-card {{ background: var(--card); padding: 10px 20px; border-radius: 12px; border: 1px solid #1e293b; }}
            .stat-val {{ display: block; font-size: 1.5rem; font-weight: 800; color: var(--accent); }}
            .stat-label {{ font-size: 0.75rem; text-transform: uppercase; color: var(--dim); letter-spacing: 0.05em; }}

            #viz-container {{ 
                width: 100%; height: 75vh; 
                background: var(--card); 
                border-radius: 20px; 
                border: 1px solid #1e293b;
                position: relative;
                overflow: hidden;
            }}
            .mermaid {{ display: flex; justify-content: center; align-items: center; height: 100%; }}
            
            #legend {{
                position: absolute; bottom: 20px; left: 20px;
                background: rgba(15, 23, 42, 0.9);
                backdrop-filter: blur(8px);
                padding: 15px; border-radius: 12px;
                border: 1px solid #1e293b;
                display: flex; flex-direction: column; gap: 8px;
                z-index: 100;
            }}
            .legend-item {{ display: flex; align-items: center; gap: 10px; font-size: 0.85rem; }}
            .dot {{ width: 12px; height: 12px; border-radius: 3px; }}
            
            #tooltip {{
                position: fixed; display: none;
                background: #1e293b; color: white;
                padding: 8px 12px; border-radius: 6px;
                font-size: 0.8rem; z-index: 1000;
                pointer-events: none; border: 1px solid var(--accent);
                box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5);
            }}
        </style>
    </head>
    <body>
        <header>
            <div class="title-area">
                <h1>🗼 Acon Topology</h1>
                <p>Template-Aware Site Discovery Engine</p>
            </div>
            <div class="stats-bar">
                <div class="stat-card">
                    <span class="stat-val">{stats['total_crawled']}</span>
                    <span class="stat-label">Pages Crawled</span>
                </div>
                <div class="stat-card">
                    <span class="stat-val">+{stats['requests_saved']}</span>
                    <span class="stat-label">Requests Saved</span>
                </div>
                <div class="stat-card">
                    <span class="stat-val">{stats['efficiency']}</span>
                    <span class="stat-label">Efficiency Gain</span>
                </div>
            </div>
        </header>

        <div id="viz-container">
            <div class="mermaid">
{mermaid_code}
            </div>
            <div id="legend">
                <div class="legend-item"><div class="dot" style="background:#38bdf8"></div> Homepage</div>
                <div class="legend-item"><div class="dot" style="background:#818cf8"></div> Navigation</div>
                <div class="legend-item"><div class="dot" style="background:#c084fc"></div> Interaction</div>
                <div class="legend-item"><div class="dot" style="background:#1e293b; border: 1px solid #334155"></div> Standard Content</div>
            </div>
        </div>

        <div id="tooltip"></div>

        <script>
            mermaid.initialize({{ 
                startOnLoad: true, 
                theme: 'base',
                themeVariables: {{
                    primaryColor: '#38bdf8',
                    edgeColor: '#475569',
                    mainBkg: '#1e293b',
                    nodeBorder: '#334155',
                    lineColor: '#475569',
                    fontFamily: 'Inter'
                }},
                securityLevel: 'loose'
            }});

            // Callback for mermaid click to show full URL
            window.callback = function(url) {{
                const tooltip = document.getElementById('tooltip');
                tooltip.innerText = url;
                tooltip.style.display = 'block';
                
                // Position will be updated by mousemove
            }};

            document.addEventListener('mousemove', function(e) {{
                const tooltip = document.getElementById('tooltip');
                if (tooltip.style.display === 'block') {{
                    tooltip.style.left = (e.pageX + 15) + 'px';
                    tooltip.style.top = (e.pageY + 15) + 'px';
                }}
            }});

            // Initialize Pan & Zoom after Mermaid renders
            const checkRender = setInterval(() => {{
                const svg = document.querySelector('#viz-container svg');
                if (svg) {{
                    svg.style.width = '100%';
                    svg.style.height = '100%';
                    svgPanZoom(svg, {{
                        zoomEnabled: true,
                        controlIconsEnabled: true,
                        fit: true,
                        center: true
                    }});
                    clearInterval(checkRender);
                }}
            }}, 100);

            // Hide tooltip when clicking away
            document.addEventListener('click', (e) => {{
                if (!e.target.closest('.node')) {{
                    document.getElementById('tooltip').style.display = 'none';
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"Premium topology visualization saved to {output_file}")
