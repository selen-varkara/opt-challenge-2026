# ╔══════════════════════════════════════════════════════════╗
# ║   Optimization Challenge 2026 - Colab Çözücü            ║
# ║   Her instance için: sol_*.json + ozet_*.txt üretir      ║
# ╚══════════════════════════════════════════════════════════╝
#
# KULLANIM:
#   1. Bu hücreyi çalıştır (Shift+Enter)
#   2. instance JSON dosyalarını yükle
#   3. solutions.zip otomatik indirilir
#      İçinde her instance için:
#        - sol_instance_X.json  (yarışmaya gönderilecek)
#        - ozet_instance_X.txt  (okunabilir özet)

import json, copy, os, zipfile
from itertools import permutations, product as iproduct
from google.colab import files

# ──────────────────────────────────────────────────────────
#  DOSYA YÜKLEME
# ──────────────────────────────────────────────────────────
print("📂 Instance dosyalarını yükleyin:")
uploaded = files.upload()
print(f"\n✅ {len(uploaded)} dosya yüklendi: {list(uploaded.keys())}\n")


# ──────────────────────────────────────────────────────────
#  ÇÖZÜCÜ FONKSİYONLAR
# ──────────────────────────────────────────────────────────

def build_tt(data):
    n  = len(data['network']['nodes'])
    TT = [[10**7]*n for _ in range(n)]
    for i in range(n): TT[i][i] = 0
    for a in data['network']['arcs']:
        TT[a['tail']][a['head']] = a['travel_time']
    return TT

def analyze_midday(data, TT):
    mid      = data['mid_day_time']
    machines = {m['id']: m for m in data['machines']}
    states   = {}
    for truck in data['trucks']:
        tid    = truck['id']
        visits = truck['route']['machine_visits']
        completed, in_prog, remaining = [], None, []
        for v in visits:
            mid_id = v.get('machine_id')
            if mid_id is None: continue
            if v['departure_time'] <= mid:             completed.append(mid_id)
            elif v['arrival_time'] < mid < v['departure_time']: in_prog = (mid_id, v)
            else:                                      remaining.append(mid_id)
        if in_prog:
            free_time = in_prog[1]['departure_time']
            free_node = machines[in_prog[0]]['node']
        elif completed:
            lv = next(v for v in visits if v.get('machine_id') == completed[-1])
            free_time = lv['departure_time']
            free_node = machines[completed[-1]]['node']
        else:
            free_time = mid
            free_node = data['depot_node_id']
        states[tid] = {'free_time': free_time, 'free_node': free_node,
                       'completed': set(completed),
                       'in_progress': in_prog[0] if in_prog else None,
                       'remaining': remaining}
    return states

def get_tasks(data, states):
    machines = {m['id']: m for m in data['machines']}
    mid      = data['mid_day_time']
    orig_truck = {}
    for truck in data['trucks']:
        for v in truck['route']['machine_visits']:
            if 'machine_id' in v: orig_truck[v['machine_id']] = truck['id']
    repl_done, repair_done = set(), set()
    for truck in data['trucks']:
        for v in truck['route']['machine_visits']:
            mid_id = v.get('machine_id')
            if not mid_id or v['departure_time'] > mid: continue
            ops = v.get('operations', [])
            if 'Replenishment' in ops: repl_done.add(mid_id)
            if 'Repair'        in ops: repair_done.add(mid_id)
    seen, tasks = set(), {}

    def add(mid_id):
        if mid_id in seen: return
        seen.add(mid_id)
        m = machines[mid_id]; failed = 'failed_at' in m
        if failed and mid_id in repl_done and mid_id not in repair_done:
            ops, dur, tb = ['Repair'], m['failure_service_duration'], False
        elif failed and mid_id not in repair_done:
            ops = ['Repair', 'Replenishment']
            dur = m['replenishment_service_duration'] + m['failure_service_duration']
            tb  = False
        else:
            ops, dur, tb = ['Replenishment'], m['replenishment_service_duration'], True
        tasks[mid_id] = {'ops': ops, 'duration': dur, 'tw_binding': tb,
                         'skippable': failed, 'orig_truck': orig_truck.get(mid_id, 0),
                         'node': m['node'], 'tw': m['time_window'],
                         'failed': failed, 'failed_at': m.get('failed_at'),
                         'demand': m.get('demand_rate', 1)}

    for m in data['machines']:
        if 'failed_at' not in m or m['id'] in repair_done: continue
        in_rem = any(m['id'] in states[t['id']]['remaining'] for t in data['trucks'])
        if not in_rem: add(m['id'])
    for truck in data['trucks']:
        for mid_id in states[truck['id']]['remaining']: add(mid_id)
    return tasks

def simulate(truck_id, sequence, tasks, states, TT, depot, day_end):
    st = states[truck_id]
    cur_node, cur_time = st['free_node'], st['free_time']
    results = []
    for mid in sequence:
        t      = tasks[mid]
        travel = TT[cur_node][t['node']]
        arr    = cur_time + travel
        svc    = max(arr, t['tw'][0]) if t['tw_binding'] else arr
        if t['tw_binding'] and svc > t['tw'][1]: return None
        dep = svc + t['duration']
        results.append((mid, arr, svc, dep, t['ops']))
        cur_node = t['node']; cur_time = dep
    if cur_time + TT[cur_node][depot] > day_end: return None
    return results

def calc_penalty(r0, r1, seq0, seq1, tasks, data):
    lf, ld, de = data['lambda_f'], data['lambda_d'], data['day_end']
    repair_time = {}
    for mid, arr, ss, dep, ops in ((r0 or []) + (r1 or [])):
        if 'Repair' in ops and mid not in repair_time: repair_time[mid] = ss
    fp = sum(m['demand_rate'] * (repair_time.get(m['id'], de*2) - m['failed_at'])
             for m in data['machines'] if 'failed_at' in m)
    dp = (sum(1 for mid in (seq0 or []) if tasks[mid]['orig_truck'] != 0) +
          sum(1 for mid in (seq1 or []) if tasks[mid]['orig_truck'] != 1))
    return lf*fp + ld*dp, fp, dp

def best_order(truck_id, assignment, tasks, states, TT, depot, day_end):
    if not assignment:
        return [], simulate(truck_id, [], tasks, states, TT, depot, day_end)
    failed = [m for m in assignment if tasks[m]['failed']]
    normal = [m for m in assignment if not tasks[m]['failed']]
    n_edf  = sorted(normal, key=lambda m: tasks[m]['tw'][1])
    n_esf  = sorted(normal, key=lambda m: tasks[m]['tw'][0])
    f_perms = list(permutations(failed)) if len(failed) <= 3 else [tuple(failed)]
    n_perms = list(permutations(normal)) if len(normal) <= 8 else [n_edf, n_esf]
    seen_k, cands = set(), []
    for base in [sorted(assignment, key=lambda m: tasks[m]['tw'][1]), n_edf + failed]:
        k = tuple(base)
        if k not in seen_k: seen_k.add(k); cands.append(base)
    for fp_ in f_perms:
        for np_ in n_perms:
            seq = list(fp_) + list(np_); k = tuple(seq)
            if k not in seen_k: seen_k.add(k); cands.append(seq)
    best_seq, best_r, best_cost = None, None, float('inf')
    for seq in cands:
        r = simulate(truck_id, seq, tasks, states, TT, depot, day_end)
        if r is None: continue
        cost = sum(tasks[mid]['demand'] * (ss - tasks[mid]['failed_at'])
                   for mid, arr, ss, dep, ops in r
                   if 'Repair' in ops and tasks[mid]['failed_at'] is not None)
        if best_r is None or cost < best_cost:
            best_cost, best_seq, best_r = cost, seq, r
    return best_seq, best_r

def optimize(data):
    TT      = build_tt(data)
    depot   = data['depot_node_id']
    day_end = data['day_end']
    states  = analyze_midday(data, TT)
    tasks   = get_tasks(data, states)
    task_ids   = list(tasks.keys())
    failed_ids = [m for m in task_ids if tasks[m]['skippable']]
    normal_ids = [m for m in task_ids if not tasks[m]['skippable']]
    N_f, N_n   = len(failed_ids), len(normal_ids)
    combo      = (3**N_f) * (2**N_n)
    best_score = float('inf')
    best_r0 = best_r1 = best_s0 = best_s1 = best_skip = None

    if combo <= 500_000:
        for f_bits in iproduct([0,1,2], repeat=N_f):
            for n_bits in iproduct([0,1], repeat=N_n):
                a0 = ([failed_ids[i] for i in range(N_f) if f_bits[i]==0] +
                      [normal_ids[i] for i in range(N_n) if n_bits[i]==0])
                a1 = ([failed_ids[i] for i in range(N_f) if f_bits[i]==1] +
                      [normal_ids[i] for i in range(N_n) if n_bits[i]==1])
                skipped = {failed_ids[i] for i in range(N_f) if f_bits[i]==2}
                s0, r0 = best_order(0, a0, tasks, states, TT, depot, day_end)
                if r0 is None: continue
                s1, r1 = best_order(1, a1, tasks, states, TT, depot, day_end)
                if r1 is None: continue
                sc, fp, dp = calc_penalty(r0, r1, s0, s1, tasks, data)
                if sc < best_score:
                    best_score = sc
                    best_r0, best_r1, best_s0, best_s1, best_skip = r0, r1, s0, s1, skipped
    else:
        a0 = [m for m in task_ids if tasks[m]['orig_truck']==0]
        a1 = [m for m in task_ids if tasks[m]['orig_truck']==1]
        s0, r0 = best_order(0, a0, tasks, states, TT, depot, day_end)
        s1, r1 = best_order(1, a1, tasks, states, TT, depot, day_end)
        skipped = set()
        if r0 and r1:
            best_score = calc_penalty(r0, r1, s0, s1, tasks, data)[0]
            best_r0, best_r1, best_s0, best_s1, best_skip = r0, r1, s0, s1, skipped
        improved = True
        while improved:
            improved = False
            for mid in task_ids:
                in0 = mid in a0; in1 = mid in a1
                actions = ['0->1','1->0']
                if tasks[mid]['skippable']:
                    if in0: actions.append('0->skip')
                    if in1: actions.append('1->skip')
                if mid in (best_skip or set()): actions += ['skip->0','skip->1']
                for action in actions:
                    na0, na1, ns = list(a0), list(a1), set(best_skip or set())
                    if   action=='0->1'    and in0: na0.remove(mid); na1.append(mid)
                    elif action=='1->0'    and in1: na1.remove(mid); na0.append(mid)
                    elif action=='0->skip' and in0: na0.remove(mid); ns.add(mid)
                    elif action=='1->skip' and in1: na1.remove(mid); ns.add(mid)
                    elif action=='skip->0':         ns.discard(mid); na0.append(mid)
                    elif action=='skip->1':         ns.discard(mid); na1.append(mid)
                    else: continue
                    ns0, nr0 = best_order(0, na0, tasks, states, TT, depot, day_end)
                    if nr0 is None: continue
                    ns1, nr1 = best_order(1, na1, tasks, states, TT, depot, day_end)
                    if nr1 is None: continue
                    sc = calc_penalty(nr0, nr1, ns0, ns1, tasks, data)[0]
                    if sc < best_score:
                        best_score = sc
                        best_r0, best_r1, best_s0, best_s1, best_skip = nr0, nr1, ns0, ns1, ns
                        a0, a1 = na0, na1; improved = True

    if best_r0 is None:
        best_r0, best_r1, best_s0, best_s1, best_skip = [], [], [], [], set()
    return best_r0, best_r1, best_s0, best_s1, best_score, best_skip, tasks, states, TT

def build_json(data, r0, r1, states, TT):
    sol      = copy.deepcopy(data)
    mid      = data['mid_day_time']
    depot    = data['depot_node_id']
    machines = {m['id']: m for m in data['machines']}
    for truck in sol['trucks']:
        tid     = truck['id']
        new_leg = (r0 if tid==0 else r1) or []
        kept    = []
        for v in truck['route']['machine_visits']:
            mid_id = v.get('machine_id')
            if mid_id is None and v['arrival_time']==0: kept.append(v); continue
            if mid_id is None: continue
            if v['departure_time']<=mid or (v['arrival_time']<mid<v['departure_time']):
                kept.append(v)
        for mid_id, arr, svc, dep, ops in new_leg:
            node_id = machines[mid_id]['node']
            kept.append({'arrival_time': arr, 'service_start_time': svc,
                         'departure_time': dep, 'operations': ops,
                         'machine_id': mid_id, 'node_id': node_id})
        if new_leg:
            last_id, _, _, last_dep, _ = new_leg[-1]
            last_node = machines[last_id]['node']
        else:
            last_dep  = states[tid]['free_time']
            last_node = states[tid]['free_node']
        da = last_dep + TT[last_node][depot]
        kept.append({'arrival_time': da, 'service_start_time': da,
                     'departure_time': da, 'operations': [], 'node_id': depot})
        truck['route']['machine_visits'] = kept
    return sol

def build_ozet(data, sol, r0, r1, s0, s1, tasks, repair_t, fp, dp, total, filename):
    machines_d = {m['id']: m for m in data['machines']}
    mid        = data['mid_day_time']
    de         = data['day_end']
    lf, ld     = data['lambda_f'], data['lambda_d']

    orig = {}
    for truck in data['trucks']:
        for v in truck['route']['machine_visits']:
            if 'machine_id' in v: orig[v['machine_id']] = truck['id']

    deviations = []
    for truck in sol['trucks']:
        tid = truck['id']
        for v in truck['route']['machine_visits']:
            m_id = v.get('machine_id')
            if m_id and v['arrival_time'] >= mid and orig.get(m_id) != tid:
                deviations.append((m_id, orig.get(m_id), tid))

    L = []
    L.append("=" * 55)
    L.append(f"ÇÖZÜM ÖZETİ — {filename}")
    L.append("=" * 55)
    L.append(f"Objective  : {total:.1f}")
    L.append(f"  Failure  : {lf} x {fp} = {lf*fp:.1f}")
    L.append(f"  Deviation: {ld} x {dp} = {ld*dp:.1f}")
    L.append("")

    L.append("ARIZALI MAKİNELER")
    L.append("-" * 55)
    for m in data['machines']:
        if 'failed_at' not in m: continue
        am  = repair_t.get(m['id'])
        pen = m['demand_rate'] * ((am if am else de*2) - m['failed_at'])
        if am:
            L.append(f"  M{m['id']:2d}  ariza=t{m['failed_at']:4d}  tamir=t{am:4d}  demand={m['demand_rate']}  ceza={pen}")
        else:
            L.append(f"  M{m['id']:2d}  ariza=t{m['failed_at']:4d}  tamir=YAPILMADI  demand={m['demand_rate']}  ceza={pen}  ← UYARI")

    L.append("")
    L.append(f"ARAÇ DEĞİŞİMLERİ (DP={dp})")
    L.append("-" * 55)
    if deviations:
        for m_id, ft, tt_ in deviations:
            L.append(f"  M{m_id}: Araç {ft} → Araç {tt_}")
    else:
        L.append("  Yok")

    L.append("")
    for truck in sol['trucks']:
        tid = truck['id']
        L.append(f"ARAÇ {tid} ROTASI")
        L.append("-" * 55)
        for v in truck['route']['machine_visits']:
            m_id = v.get('machine_id')
            ops  = '+'.join(v.get('operations', []))
            svc  = v['service_start_time']
            tag  = " ← YENİ" if v['arrival_time'] >= mid else ""
            if m_id is None:
                L.append(f"  t={svc:4d}  DEPOT{tag}")
            else:
                tw = machines_d[m_id]['time_window']
                L.append(f"  t={svc:4d}  M{m_id:2d}  {ops:25s}  tw={tw}{tag}")
        L.append("")

    return "\n".join(L)


# ──────────────────────────────────────────────────────────
#  ÇÖZME DÖNGÜSÜ
# ──────────────────────────────────────────────────────────
results_summary = []

for filename, content in uploaded.items():
    if not filename.endswith('.json'): continue

    print(f"{'='*55}")
    print(f"⚙️  {filename} çözülüyor...")

    data = json.loads(content.decode('utf-8'))
    r0, r1, s0, s1, score, skipped, tasks, states, TT = optimize(data)

    de = data['day_end']; lf, ld = data['lambda_f'], data['lambda_d']
    repair_t = {}
    for mid, arr, ss, dep, ops in ((r0 or []) + (r1 or [])):
        if 'Repair' in ops and mid not in repair_t: repair_t[mid] = ss
    fp = sum(m['demand_rate'] * (repair_t.get(m['id'], de*2) - m['failed_at'])
             for m in data['machines'] if 'failed_at' in m)
    dp = (sum(1 for mid in (s0 or []) if tasks[mid]['orig_truck']!=0) +
          sum(1 for mid in (s1 or []) if tasks[mid]['orig_truck']!=1))
    total = lf*fp + ld*dp

    print(f"✅  Objective = {total:.1f}  (FP={lf*fp:.1f}, DP={ld*dp:.1f})")
    if skipped: print(f"   Bırakılan arızalar: M{sorted(skipped)}")

    # 1) Yarışmaya gönderilecek JSON
    sol      = build_json(data, r0, r1, states, TT)
    out_json = filename.replace('instance_', 'sol_instance_')
    with open(out_json, 'w') as f:
        json.dump(sol, f, indent=2)

    # 2) Okunabilir özet TXT
    ozet_txt  = filename.replace('instance_', 'ozet_instance_').replace('.json', '.txt')
    ozet_icerik = build_ozet(data, sol, r0, r1, s0, s1, tasks, repair_t, fp, dp, total, filename)
    with open(ozet_txt, 'w', encoding='utf-8') as f:
        f.write(ozet_icerik)

    print(f"   📄 {out_json}  +  📋 {ozet_txt}")
    results_summary.append((filename, out_json, ozet_txt, total))

# ──────────────────────────────────────────────────────────
#  ÖZET TABLO
# ──────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print("📊 ÖZET")
print(f"{'='*55}")
print(f"{'Instance':<22} {'Objective':>10}")
print(f"{'-'*34}")
for inp, out_j, out_t, sc in sorted(results_summary):
    print(f"{inp:<22} {sc:>10.1f}")

# ──────────────────────────────────────────────────────────
#  ZIP İNDİR (JSON + TXT birlikte)
# ──────────────────────────────────────────────────────────
zip_name = "solutions.zip"
with zipfile.ZipFile(zip_name, 'w') as zf:
    for _, out_j, out_t, _ in results_summary:
        if os.path.exists(out_j): zf.write(out_j)
        if os.path.exists(out_t): zf.write(out_t)

print(f"\n📦 {zip_name} indiriliyor...")
files.download(zip_name)
print("✅ Bitti!")
