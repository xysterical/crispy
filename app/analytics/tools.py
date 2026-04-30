ANALYTICS_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_product_sales_velocity",
            "description": "分析指定商品的销售速度趋势。返回近期日均销量、环比变化、趋势方向（上升/稳定/下降）和统计置信度。需要至少7天的销售数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": {
                        "type": "string",
                        "description": "商品代码，用于查询该商品的销售数据",
                    },
                    "window_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "分析的时间窗口（天），默认30天",
                    },
                },
                "required": ["product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_product_contribution",
            "description": "分析多个商品的营收贡献度（帕累托分析）。识别英雄品（贡献80%营收的top商品）和长尾品（贡献<5%的商品）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要分析的商品代码列表，不提供则分析所有商品",
                    },
                    "period_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "分析的时间窗口（天）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_creative_fatigue",
            "description": "检测指定创意的疲劳度。通过分析每日CTR的线性趋势判断创意是否在衰退。如果CTR持续下降（p<0.05），判定为疲劳，并估算剩余有效天数。同时检测CPC是否同步上升。",
            "parameters": {
                "type": "object",
                "properties": {
                    "creative_key": {
                        "type": "string",
                        "description": "创意标识符（ad_id 或 creative_id）",
                    },
                    "window_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "分析的时间窗口（天）",
                    },
                },
                "required": ["creative_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_creatives",
            "description": "对比多个创意的表现。使用Wilson Score Interval对CTR做区间估计，区间不重叠判定为统计显著差异。对CPA/ROAS使用bootstrap置信区间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "creative_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要对比的创意标识符列表",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["ctr", "cpa", "roas"],
                        "default": "ctr",
                        "description": "对比指标",
                    },
                },
                "required": ["creative_keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_ad_sales_lag",
            "description": "分析广告花费到商品销售的转化时滞。使用互相关函数（CCF）找最佳时间延迟。lag=0-1天为冲动型消费，2-4天为考虑型消费，>4天为不确定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": {
                        "type": "string",
                        "description": "商品代码",
                    },
                    "max_lag_days": {
                        "type": "integer",
                        "default": 7,
                        "description": "最大延迟天数",
                    },
                },
                "required": ["product_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_spend_efficiency",
            "description": "分析创意的投放效率。计算累计花费vs边际ROAS，找到边际ROAS低于1.0的饱和点，帮助控制单创意日预算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "creative_key": {
                        "type": "string",
                        "description": "创意标识符",
                    },
                    "window_days": {
                        "type": "integer",
                        "default": 30,
                        "description": "分析的时间窗口（天）",
                    },
                },
                "required": ["creative_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_product_bundles",
            "description": "分析商品关联购买关系。基于订单共现数据计算商品对的support/confidence/lift，识别经常一起购买的商品组合。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_code": {
                        "type": "string",
                        "description": "目标商品代码",
                    },
                    "min_cooccurrence": {
                        "type": "integer",
                        "default": 3,
                        "description": "最小共现次数阈值",
                    },
                },
                "required": ["product_code"],
            },
        },
    },
]
