---
title: "反例：格式漂移与定位错误必须被拦下"
type: distill-report
branch: paper
platform: paper
source: "https://arxiv.org/abs/1706.03762"
source_title: "Attention Is All You Need"
author: "Vaswani et al."
published: "2023-08-02"
fetched: "2026-11-13T10:00:00+08:00"
tags:
  - "知识库/人工智能"
status: draft
confidence: high
coverage: 0.9
raw_chars: 620
summary_chars: 300
related:
  - "[[00-知识库总纲]]"
---

# 反例：定位错误的四种写法

## 0. 一句话结论

这四条锚点看起来都能查，实际一条都查不到。{S} [p.3 §3 "the first sequence transduction model based entirely on attention"]

## 1. 核心主张

| # | 主张 | 支持度 | 定位 |
|---|------|--------|------|
| 1 | 节号不存在时要报错 {S} | S | [p.2 §9.9 "relating different positions of a single sequence"] |
| 2 | 页码与节矛盾时要报错 {S} | S | [p.3 §2.1 "relating different positions of a single sequence"] |
| 3 | 表格行写成「行 A」要报错 {S} | S | [p.2 Table 1 行 A] |
| 4 | 无 § 的节名要报错 {S} | S | [p.2 Background] |

<!-- thin-ok 本用例只验定位错误，不验内容密度 -->

## 6. 局限与未证明

<!-- thin-ok 反例不涉及局限 -->

## 7. 我的判断（主观，非原文）

<!-- thin-ok 反例不涉及判断 -->

## 附：定位表

| ID | 位置 | 原文前 20 字 |
|----|------|-------------|
| p.3 §3 | 结论 | We propose the Transformer, the first |
