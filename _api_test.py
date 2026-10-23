"""Web API 完整链路测试"""
import requests
import time

BASE = "http://127.0.0.1:8000"


def main():
    print("=== 1. 创建项目 ===", flush=True)
    r = requests.post(
        f"{BASE}/api/projects/",
        json={"title": "雾中旅人Web", "style": "克制、悬疑、第三人称有限视角"},
        timeout=10,
    )
    assert r.status_code == 200, f"创建项目失败: {r.status_code} {r.text}"
    pid = r.json()["project_id"]
    print(f"✅ project_id={pid}", flush=True)

    print("=== 2. 创建角色 ===", flush=True)
    chars = [
        {"name": "林夏", "importance_tier": "primary", "persona": "冷静、善于隐藏情绪，习惯用反问句", "motivation": "寻找失踪的姐姐", "secrets": "她其实知道姐姐去向，但故意装作不知情"},
        {"name": "阿泽", "importance_tier": "secondary", "persona": "话多、爱打探消息", "motivation": "想从林夏这里套出情报换钱"},
        {"name": "旅店老板", "importance_tier": "background", "persona": "沉默寡言，偶尔目光犀利", "motivation": "只想息事宁人，但似乎知道些什么"},
    ]
    for c in chars:
        r = requests.post(
            f"{BASE}/api/projects/{pid}/assets/characters",
            json=c,
            timeout=10,
        )
        status = "✅" if r.status_code == 200 else f"❌ {r.status_code}"
        print(f"  {status} {c['name']}", flush=True)

    print("=== 3. 生成场景（预计 3-5 分钟） ===", flush=True)
    body = {
        "project_id": pid,
        "scene_brief": "林夏在雾港旅店大堂被阿泽搭讪，试探她是否知道姐姐下落。旅店老板在柜台后面擦杯子，偶尔抬头看一眼。",
        "present_character_names": ["林夏", "阿泽", "旅店老板"],
    }
    t0 = time.time()
    r = requests.post(f"{BASE}/api/generate/scene", json=body, timeout=420)
    elapsed = time.time() - t0
    print(f"⏱️ 耗时 {elapsed:.1f}s  状态码 {r.status_code}", flush=True)

    if r.status_code == 200:
        data = r.json()
        prose = data.get("final_prose", "")
        print(f"✅ 生成成功！正文字数 {len(prose)}", flush=True)
        print("--- 正文前 1500 字 ---", flush=True)
        print(prose[:1500], flush=True)
        print("--- 伏笔更新 ---", flush=True)
        for f in data.get("foreshadowing_updates", []):
            print(f"  [{f['status']}] {f['description'][:60]}...", flush=True)
        print("--- Agent 执行步骤 ---", flush=True)
        for s in data.get("steps", [])[:10]:
            print(f"  {s['agent_name']} → {s['model_used']} [{s['status']}]", flush=True)
    else:
        print(f"❌ 失败: {r.text[:800]}", flush=True)


if __name__ == "__main__":
    main()
