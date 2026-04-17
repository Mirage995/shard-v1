import sqlite3, json

conn = sqlite3.connect('shard_memory/shard.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT id, topic, statement, experiment_result, rationale, status FROM research_hypotheses WHERE id IN (9, 11, 14, 16, 41)').fetchall()

for r in rows:
    print(f"--- ID {r['id']} ({r['status']}) ---")
    print(f"Topic: {r['topic']}")
    print(f"Statement: {r['statement']}\n")
    print(f"Rationale: {r['rationale']}\n")
    res = r['experiment_result']
    if res:
        try:
            res_obj = json.loads(res)
            print(f"Result (Success): {res_obj.get('success')}")
            print(f"Stdout (partial): {str(res_obj.get('stdout'))[:1000]}...")
        except:
            print(f"Result (Raw): {str(res)[:1000]}...")
    else:
        print("Experiment Result: None (not yet run or planned externally)")
    print("\n" + "="*50 + "\n")
