import json
import math
import itertools
import pandas as pd
import os

# INSTANCE DOSYASINI OKU
with open("instances/instance_1.json") as f:
    data = json.load(f)

# NODE KOORDINATLARI
nodes = {n["id"]: (n["x"], n["y"]) for n in data["network"]["nodes"]}

midday = data["mid_day_time"]
lambda_f = data["lambda_f"]
lambda_d = data["lambda_d"]

# FAILURELARI BUL
failures = [m for m in data["machines"] if "failed_at" in m and m["failed_at"] <= midday]

# TRUCK KONUMUNU BUL
truck_pos = []

for t in data["trucks"]:

    visits = t["route"]["machine_visits"]

    last_node = visits[0]["node_id"]
    last_depart = visits[0]["departure_time"]

    for v in visits:

        if v["departure_time"] <= midday:
            last_node = v["node_id"]
            last_depart = v["departure_time"]
        else:
            break

    truck_pos.append({
        "truck": t["id"],
        "node": last_node,
        "time": last_depart
    })

# ORIJINAL ATAMALARI BUL
machine_original = {}

for t in data["trucks"]:
    for v in t["route"]["machine_visits"]:
        if "machine_id" in v:
            machine_original[v["machine_id"]] = t["id"]

# MESAFE FONKSIYONU
def dist(a, b):

    ax, ay = nodes[a]
    bx, by = nodes[b]

    return math.sqrt((ax - bx)**2 + (ay - by)**2)

results = []

trucks = [t["truck"] for t in truck_pos]

# TÜM OLASI ATAMALARI DENE
for assign in itertools.product(trucks, repeat=len(failures)):

    state = {t["truck"]: {"node": t["node"], "time": t["time"]} for t in truck_pos}

    failure_pen = 0
    deviation = 0

    for f, truck in zip(failures, assign):

        node = f["node"]
        fail_time = f["failed_at"]
        demand = f["demand_rate"]
        repair = f["failure_service_duration"]

        cur_node = state[truck]["node"]
        cur_time = state[truck]["time"]

        travel = dist(cur_node, node)

        arrival = cur_time + travel
        start = arrival
        finish = start + repair

        state[truck]["node"] = node
        state[truck]["time"] = finish

        failure_pen += demand * (start - fail_time)

        if f["id"] in machine_original and machine_original[f["id"]] != truck:
            deviation += 1

    obj = lambda_f * failure_pen + lambda_d * deviation

    results.append({
        "assignment": assign,
        "failure_penalty": failure_pen,
        "deviation_penalty": deviation,
        "objective": obj
    })

df = pd.DataFrame(results)

best = df.sort_values("objective").iloc[0]

print("FAILURES:")
print(pd.DataFrame(failures)[["id","node","failed_at","demand_rate"]])

print("\nTRUCK POSITIONS:")
print(pd.DataFrame(truck_pos))

print("\nBEST SOLUTION:")
print(best)

print("\nALL SOLUTIONS:")
print(df.sort_values("objective"))

# SOLUTION KLASÖRÜ OLUŞTUR
os.makedirs("solutions", exist_ok=True)

solution = {
    "assignment": list(best["assignment"]),
    "objective": float(best["objective"])
}

# JSON DOSYASI YAZ
with open("solutions/sol_instance_1.json", "w") as f:
    json.dump(solution, f, indent=4)

print("\nSolution file saved in solutions/sol_instance_1.json")