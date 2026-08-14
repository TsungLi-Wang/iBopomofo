#!/usr/bin/env python3
# 從 taiwan-mandarin-dataset 的 contexts **dev 側** 造一份評分機吃得下的題庫，
# 專門用來定節點層模型的棄權門檻（docs/decisions/0008 第六節）。
#
# ## 為什麼一定要有這份
#
# 門檻直接決定「模型什麼時候敢出手」。在兩份 i注音真實語料上掃門檻、挑最高的
# 報出去，就是 docs/dead-ends.md B 節那條「同一份資料選參數又報成績」——
# 那個錯誤在這個專案換皮出現過五次，同一機制數字差三倍。
#
# 所以：**門檻在這份 dev 上定，定完就不准再動**，然後拿去真實語料量一次。
# 這份 dev 與訓練集用同一個 doc hash 切開（build_node_homophone_data.py 的
# is_dev），所以模型沒看過。
#
# ## 注音怎麼來
#
# 用引擎自己的 BPMFMappings.txt 做最長詞優先切分，取出每個字的讀音；
# 詞表裡切不到的單字退回 data.txt 的「該字最高頻讀音」（BPMFMappings 只收詞、
# 不收單字，沒有這層退路的話一句都造不出來）。
# 切不出來、音節數對不上、或目標位讀音 ≠ contexts 的 input_zhuyin 的句子
# 一律丟掉（沿用 build_natural_validation.py 的守則：目標字在這句讀別的音
# → 使用者根本打不到這個混淆，那題不算數）。
#
# PTT 原句夾雜空白、標點、英數，評分機吃的是純漢字句，所以先把目標字所在的
# **最長連續漢字段** 切出來當這一題的句子（太短的丟掉，上下文不夠就不是題）。
#
# ⚠️ 這份是 **dev，不是尺**。不得拿它宣稱好壞、也不得進 CHANGELOG。

import argparse
import hashlib
import json
import os
import re

HAN = re.compile(r'[一-鿿]')
DE_GROUP = '的得地'


def load_mappings(path):
    """詞 → 讀音陣列；同時記最長詞長，供最長詞優先切分用。"""
    m = {}
    longest = 1
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            parts = line.rstrip('\n').split(' ')
            if len(parts) < 2:
                continue
            word, readings = parts[0], parts[1:]
            if len(word) != len(readings):
                continue
            m.setdefault(word, readings)
            longest = max(longest, len(word))
    return m, longest


def load_char_readings(path):
    """data.txt 的單字 → 最高頻讀音（多音字取詞庫裡權重最大的那個）。"""
    best = {}
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if line.startswith('#'):
                continue
            f = line.rstrip('\n').split(' ')
            if len(f) < 3:
                continue
            reading, value = f[0], f[1]
            if len(value) != 1 or not HAN.match(value) or '-' in reading:
                continue
            try:
                score = float(f[2])
            except ValueError:
                continue
            if value not in best or score > best[value][1]:
                best[value] = (reading, score)
    return {k: v[0] for k, v in best.items()}


def annotate(sentence, mappings, longest, char_readings):
    """回傳每個字的讀音；有任何一個字切不出來就回 None。"""
    out = []
    i = 0
    n = len(sentence)
    while i < n:
        hit = None
        for size in range(min(longest, n - i), 0, -1):
            word = sentence[i:i + size]
            if word in mappings:
                hit = (word, mappings[word])
                break
        if hit is None:
            if HAN.match(sentence[i]):
                fallback = char_readings.get(sentence[i])
                if fallback is None:
                    return None  # 連單字讀音都查不到 → 整句不要
                out.append(fallback)
                i += 1
                continue
            out.append(None)     # 標點、空白、英數 —— 不是要量的東西
            i += 1
            continue
        out.extend(hit[1])
        i += len(hit[0])
    return out


def han_span(sentence, index):
    """目標字所在的最長連續漢字段 → (子句, 目標在子句裡的位置)。"""
    if not HAN.match(sentence[index]):
        return None, -1
    start = index
    while start > 0 and HAN.match(sentence[start - 1]):
        start -= 1
    end = index + 1
    while end < len(sentence) and HAN.match(sentence[end]):
        end += 1
    return sentence[start:end], index - start


def is_dev(doc_id, frac=0.05):
    h = int(hashlib.sha256(doc_id.encode()).hexdigest()[:8], 16)
    return (h % 1000) < int(frac * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default=os.path.expanduser(
        '~/Documents/taiwan-mandarin-dataset'))
    ap.add_argument('--mappings', default='Source/Data/BPMFMappings.txt')
    ap.add_argument('--data-txt', default='Source/Data/data.txt')
    ap.add_argument('--frozen', default=None)
    ap.add_argument('--out', required=True)
    ap.add_argument('--dev-frac', type=float, default=0.05)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--min-len', type=int, default=8)
    args = ap.parse_args()

    frozen_path = args.frozen or os.path.join(
        args.dataset, 'benchmark/FROZEN_HASHES.json')
    frozen = set(json.load(open(frozen_path, encoding='utf-8'))['hashes'])
    mappings, longest = load_mappings(args.mappings)
    char_readings = load_char_readings(args.data_txt)

    ctx = os.path.join(args.dataset, 'analysis/homophones/contexts.jsonl')
    kept, skip = [], {}

    def bump(k):
        skip[k] = skip.get(k, 0) + 1

    with open(ctx, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            if not is_dev(r['source_doc_id'], args.dev_frac):
                continue
            if r['target_group'] == DE_GROUP:
                bump('的得地（標籤髒，不當 gold）')
                continue
            sent = (r.get('full_sentence_hint') or '').strip()
            if not sent:
                bump('沒有句子')
                continue
            if hashlib.sha256(sent.encode()).hexdigest() in frozen:
                bump('命中 FROZEN_HASHES')
                continue
            idx = sent.find(r['left_context'] + r['target'] + r['right_context'])
            if idx < 0:
                bump('左右文對不回原句')
                continue
            sent, target_index = han_span(sent, idx + len(r['left_context']))
            if sent is None:
                bump('目標位不是漢字')
                continue
            if len(sent) < args.min_len:
                bump(f'漢字段太短（<{args.min_len}）')
                continue
            readings = annotate(sent, mappings, longest, char_readings)
            if readings is None or len(readings) != len(sent):
                bump('注音切不出來／音節數對不上')
                continue
            if readings[target_index] != r['input_zhuyin']:
                bump('目標位讀音不符')
                continue
            if any(x is None for x in readings):
                bump('句中有非漢字')
                continue
            cands = [c for c in r['candidates'] if c != r['target']]
            kept.append({
                'sentence_id': f'CTXDEV-{len(kept) + 1:05d}',
                'sentence': sent,
                'target_index': target_index,
                'target_char': r['target'],
                'wrong_chars': cands,
                'reading': r['input_zhuyin'],
                'pair_id': r['target_group'],
                'n_way': len(r['candidates']),
                'weight': 1.0,
                'tier': 'single',
                'split': 'heldout',
                'domain': 'ctxdev-ptt',
                'full_reading': '-'.join(readings),
                'source': 'taiwan-mandarin-dataset-contexts-dev',
            })
            if args.limit and len(kept) >= args.limit:
                break

    with open(args.out, 'w', encoding='utf-8') as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'寫出 {len(kept)} 題 → {args.out}')
    for k, v in sorted(skip.items(), key=lambda x: -x[1]):
        print(f'  略過 {k}: {v}')


if __name__ == '__main__':
    main()
