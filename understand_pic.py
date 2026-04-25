import os
import base64

from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("CRISPY_API_KEY_KIMI"),
    base_url="https://api.moonshot.cn/v1",
)

# 在这里，你需要将 kimi.png 文件替换为你想让 Kimi 识别的图片的地址
image_path = "fortest/leash.png"

with open(image_path, "rb") as f:
    image_data = f.read()

# 我们使用标准库 base64.b64encode 函数将图片编码成 base64 格式的 image_url
image_url = f"data:image/{os.path.splitext(image_path)[1].lstrip('.')};base64,{base64.b64encode(image_data).decode('utf-8')}"


completion = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "system", "content": "你是 Kimi。"},
        {
            "role": "user",
            # 注意这里，content 由原来的 str 类型变更为一个 list，这个 list 中包含多个部分的内容，图片（image_url）是一个部分（part），
            # 文字（text）是一个部分（part）
            "content": [
                {
                    "type": "image_url", # <-- 使用 image_url 类型来上传图片，内容为使用 base64 编码过的图片内容
                    "image_url": {
                        "url": image_url,
                    },
                },
                {
                    "type": "text",
                    "text": "请描述图片的内容。", # <-- 使用 text 类型来提供文字指令，例如"描述图片内容"
                },
            ],
        },
    ],
)

print(completion.choices[0].message.content)

# 这是一张**宠物牵引绳（狗绳）**的产品照片，背景为纯白色，突出展示了绳子的细节。
# 牵引绳主体由一根**彩色编织圆绳**制成，绳面上交织着**橙色、紫色、蓝色和黄色**等多种颜色，形成富有活力的花纹。绳子被盘绕成圈状摆放。
# 具体结构包括：
# *   **顶部握把**：绳子一端回折形成一个结实的绳圈，作为手持握把。
# *   **绳体配件**：绳子上带有一个**黑色的塑料或橡胶部件**，可能起到防滑握把、缓冲或固定的作用；附近还能看到连接着一个**银色的金属圆环（O型环）**。
# *   **末端连接扣**：绳子另一端配有一个**银色金属弹簧钩扣（登山扣样式）**，用于连接狗狗的项圈或胸背带。
# 整体来看，这条牵引绳设计结实耐用，色彩鲜艳，给人一种适合户外活动的感觉。