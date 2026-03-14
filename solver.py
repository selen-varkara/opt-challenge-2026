# Baseline brute force solver
# Reads instance JSON
# Assigns failures to trucks
# Computes objective with failure and deviation penaltiesss

import json
import itertools
import pandas as pd
import os

# ----------------------------
# INSTANCE DOSYASI OKU
# ----------------------------

INSTANCE_FILE = "instances/instance_1.json"

with open(INSTANCE_FILE) as f:
    data = json.load(f)

midday = data["mid_day_time"]
lambda_f = data["lambda_f"]
lambda_d = data["lambda_d"]

# ----------------------------
# NETWORK TRAVEL TIME MATRIX
# ----------------------------

travel = {}

for arc in data["network"]["arcs"]:
    i = arc["tail"]
    j = arc["head"]
    t = arc["travel_time"]
    travel[(i, j)] = t

# ----------------------------
# FAILURE MAKİNELERİ BUL
# ----------------------------

failures = []

for m in data["machines"]:
    if "failed_at" in m and m["failed_at"] <= midday:
        failures.append(m)

# ----------------------------
# TRUCK POZİSYONLARI
# ----------------------------

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

# ----------------------------
# ORJINAL ATAMALAR
# ----------------------------

machine_original = {}

for t in data["trucks"]:
    for v in t["route"]["machine_visits"]:
        if "machine_id" in v:
            machine_original[v["machine_id"]] = t["id"]

# ----------------------------
# MESAFE FONKSİYONU
# ----------------------------

def travel_time(a, b):

    if (a, b) in travel:
        return travel[(a, b)]

    return 9999


# ----------------------------
# TÜM ATAMALARI DENE
# ----------------------------

results = []

trucks = [t["truck"] for t in truck_pos]

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

        travel_t = travel_time(cur_node, node)

        arrival = cur_time + travel_t
        start = arrival
        finish = start + repair

        state[truck]["node"] = node
        state[truck]["time"] = finish

        failure_pen += demand * max(0, start - fail_time)

        if f["id"] in machine_original and machine_original[f["id"]] != truck:
            deviation += 1

    obj = lambda_f * failure_pen + lambda_d * deviation

    results.append({
        "assignment": assign,
        "failure_penalty": failure_pen,
        "deviation_penalty": deviation,
        "objective": obj
    })


# ----------------------------
# EN İYİ ÇÖZÜM
# ----------------------------

df = pd.DataFrame(results)

best = df.sort_values("objective").iloc[0]

print("FAILURES:")
print(pd.DataFrame(failures)[["id", "node", "failed_at", "demand_rate"]])

print("\nTRUCK POSITIONS:")
print(pd.DataFrame(truck_pos))

print("\nBEST SOLUTION:")
print(best)


# ----------------------------
# SOLUTION KAYDET
# ----------------------------

os.makedirs("solutions", exist_ok=True)

instance_name = os.path.basename(INSTANCE_FILE).replace("instance", "sol")

solution = {
    "assignment": list(best["assignment"]),
    "objective": float(best["objective"])
}

with open(f"solutions/{instance_name}", "w") as f:
    json.dump(solution, f, indent=4)

print("\nSolution saved:", f"solutions/{instance_name}")