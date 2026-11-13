---
title: "节级定位样例：页 + § 才能核到句"
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
  - "主题/Transformer"
status: draft
confidence: high
coverage: 0.9
raw_chars: 620
summary_chars: 979
related:
  - "[[00-知识库总纲]]"
---

# 节级定位样例

## 0. 一句话结论

Transformer 用纯注意力替换循环层，是第一个不依赖循环或卷积的序列转导模型。{S} [p.3 §3 "the first sequence transduction model based entirely on attention"]

## 1. 核心主张

| # | 主张 | 支持度 | 定位 |
|---|------|--------|------|
| 1 | 此前主流序列转导模型依赖复杂的循环或卷积网络 {S} | S | [p.1 §Abstract "based on complex recurrent or convolutional neural networks"] |
| 2 | 循环模型沿符号位置分解计算 {S} | S | [p.2 §1 "factor computation along the symbol positions"] |
| 3 | 自注意力把单个序列中不同位置关联起来 {S} | S | [p.2 §2.1 "relating different positions of a single sequence"] |

## 6. 局限与未证明

<!-- thin-ok 原文只有一句结论，没有更多未证明项 -->

- 原文未给出与同参数量卷积模型的直接对照 {M} [p.3 §3 "replacing the recurrent layers most commonly used in encoder-decoder architectures"]

## 7. 我的判断（主观，非原文）

<!-- thin-ok 判断只有一条，不灌水 -->

- 节级锚点比页级实用，因为一页上千字挑不出支撑句 {I} [p.2 §2.1 "Self-attention, sometimes called intra-attention, is an attention mechanism relating different positions of a single sequence"]

## 附：定位表

| ID | 位置 | 原文前 20 字 |
|----|------|-------------|
| p.1 §Abstract | 摘要 | The dominant sequence transduction |
| p.2 §1 | 引言 | Recurrent models typically factor |
| p.2 §2.1 | 2.1 自注意力 | Self-attention, sometimes called |
| p.3 §3 | 结论 | We propose the Transformer, the first |
