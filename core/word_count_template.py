# -*- coding: utf-8 -*-
"""
字数级别配置
根据章节字数动态配置内容元素
"""

from enum import Enum
from dataclasses import dataclass
from typing import Tuple, Dict, Any


class ChapterLevel(Enum):
    """章节级别枚举"""
    SHORT = "short"      # <2000字
    STANDARD = "standard"  # 2000-4000字
    LONG = "long"        # 4000-6000字
    EPIC = "epic"        # >6000字


@dataclass
class ChapterLevelConfig:
    """章节级别配置"""
    level: ChapterLevel
    min_words: int
    max_words: int
    node_count: Tuple[int, int]  # 情节点数范围
    hook_count: Tuple[int, int]  # 钩子数范围
    env_ratio: Tuple[int, int]  # 环境描写占比(%)
    psychological_depth: str  # 心理刻画深度: 简略/标准/深入/深度
    dialogue_density: str  # 对话密度: 较高/标准/适中/较少
    foreshadow_count: Tuple[int, int]  # 伏笔埋设数
    scene_count: Tuple[int, int]  # 场景转换数
    word_tolerance: int  # 字数宽容度


# 各级别配置
CHAPTER_LEVEL_CONFIGS = {
    ChapterLevel.SHORT: ChapterLevelConfig(
        level=ChapterLevel.SHORT,
        min_words=0,
        max_words=2000,
        node_count=(2, 3),
        hook_count=(1, 2),
        env_ratio=(5, 8),
        psychological_depth="简略",
        dialogue_density="较高",
        foreshadow_count=(0, 1),
        scene_count=(1, 2),
        word_tolerance=200
    ),
    ChapterLevel.STANDARD: ChapterLevelConfig(
        level=ChapterLevel.STANDARD,
        min_words=2000,
        max_words=4000,
        node_count=(3, 4),
        hook_count=(2, 3),
        env_ratio=(8, 12),
        psychological_depth="标准",
        dialogue_density="标准",
        foreshadow_count=(1, 2),
        scene_count=(2, 3),
        word_tolerance=300
    ),
    ChapterLevel.LONG: ChapterLevelConfig(
        level=ChapterLevel.LONG,
        min_words=4000,
        max_words=6000,
        node_count=(4, 5),
        hook_count=(3, 4),
        env_ratio=(12, 18),
        psychological_depth="深入",
        dialogue_density="适中",
        foreshadow_count=(2, 3),
        scene_count=(3, 4),
        word_tolerance=400
    ),
    ChapterLevel.EPIC: ChapterLevelConfig(
        level=ChapterLevel.EPIC,
        min_words=6000,
        max_words=99999,
        node_count=(5, 7),
        hook_count=(4, 6),
        env_ratio=(15, 20),
        psychological_depth="深度",
        dialogue_density="较少",
        foreshadow_count=(3, 5),
        scene_count=(4, 6),
        word_tolerance=500
    ),
}


def get_chapter_level(word_count: int) -> ChapterLevel:
    """根据字数获取章节级别"""
    if word_count < 2000:
        return ChapterLevel.SHORT
    elif word_count < 4000:
        return ChapterLevel.STANDARD
    elif word_count < 6000:
        return ChapterLevel.LONG
    else:
        return ChapterLevel.EPIC


def get_level_config(level: ChapterLevel) -> ChapterLevelConfig:
    """获取指定级别的配置"""
    return CHAPTER_LEVEL_CONFIGS.get(level)


def get_config_by_word_count(word_count: int) -> ChapterLevelConfig:
    """根据字数获取配置"""
    level = get_chapter_level(word_count)
    return get_level_config(level)


def format_level_prompt(level: ChapterLevel) -> str:
    """格式化级别提示词"""
    config = get_level_config(level)
    if config is None:
        return ""

    return f"""章节级别: {config.level.value}
目标字数: {config.min_words}-{config.max_words}字
情节点数: {config.node_count[0]}-{config.node_count[1]}个
钩子数: {config.hook_count[0]}-{config.hook_count[1]}条
环境描写占比: {config.env_ratio[0]}-{config.env_ratio[1]}%
心理刻画深度: {config.psychological_depth}
对话密度: {config.dialogue_density}
伏笔埋设数: {config.foreshadow_count[0]}-{config.foreshadow_count[1]}条
场景转换数: {config.scene_count[0]}-{config.scene_count[1]}个
字数宽容度: ±{config.word_tolerance}字"""


def get_level_adaptation_guide(level: ChapterLevel) -> str:
    """获取级别适配指南（用于Writer/Architect提示词）"""
    if level == ChapterLevel.SHORT:
        return """【短章节(<2000字)内容分配】
- 聚焦单一线索，快速推进情节
- 1-2个钩子即可，结尾留一个小悬念
- 环境描写点到为止，不展开
- 心理刻画简略，用行动代替心理
- 伏笔最多1条，选择立即型伏笔"""
    elif level == ChapterLevel.STANDARD:
        return """【标准章节(2000-4000字)内容分配】
- 完整起承转合结构
- 2-3个钩子（含结尾钩子）
- 标准密度伏笔，可埋1-2条
- 环境描写适中，场景转换2-3次
- 心理刻画标准，关键场景可展开"""
    elif level == ChapterLevel.LONG:
        return """【长章节(4000-6000字)内容分配】
- 多线并行或深度展开单线
- 3-4个钩子，可有次要钩子
- 较多伏笔铺垫，可埋2-3条
- 环境描写充分，场景转换3-4次
- 心理刻画深入，主要人物内心可多层次"""
    else:  # EPIC
        return """【超长章节(>6000字)内容分配】
- 核心高潮场景详细展开
- 4-6个钩子，密度高
- 可设置多层级伏笔，埋3-5条
- 环境描写丰富，场景转换4-6次
- 心理刻画深度，多视角内心描写"""