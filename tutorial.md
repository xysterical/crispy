# 快速开始

欢迎使用我们的API服务！本指南将帮助您快速开始使用图像和视频生成功能。

## 第一步：获取API密钥

1. 访问 [API密钥管理页面](https://apimart.ai/keys)
2. 登录您的账户
3. 创建新的API密钥
4. 保存您的密钥（密钥只显示一次）

## 第二步：选择模型

我们提供多种AI模型供您选择：

### 文字生成模型

* **GPT-4o**: 强大的对话和文本生成能力
* **Claude**: Anthropic 的高性能对话模型
* **Gemini**: Google 的多模态大语言模型

### 图像生成模型

* **GPT-4o-image**: 高质量图像生成

### 视频生成模型

* **Sora2**: 专业视频生成

## 第三步：发送请求

### 文字生成示例

```bash theme={null}
curl -X POST https://api.apimart.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {
        "role": "user",
        "content": "你好，请介绍一下你自己"
      }
    ]
  }'
```

### 图像生成示例

```bash theme={null}
curl -X POST https://api.apimart.ai/v1/images/generations \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-image",
    "prompt": "一只可爱的熊猫",
    "size": "1:1",
    "n": 1
  }'
```

### 视频生成示例

```bash theme={null}
curl -X POST https://api.apimart.ai/v1/videos/generations \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sora-2",
    "prompt": "海浪拍打着海岸",
    "duration": 15,
    "aspect_ratio": "16:9"
  }'
```

## 第四步：查询任务状态

由于我们使用异步处理模式，您需要查询任务状态来获取结果：

```bash theme={null}
curl -X GET https://api.apimart.ai/v1/tasks/YOUR_TASK_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## 下一步

<Card title="查看API文档" icon="book" href="/cn/api-reference/introduction">
  详细了解所有可用的API接口
</Card>

<Card title="开发指南" icon="code" href="/cn/development">
  了解如何在您的应用中集成API
</Card>


> ## Documentation Index
> Fetch the complete documentation index at: https://docs.apimart.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# GPT-Image-2 图像生成

>  - 异步处理模式，返回任务ID用于后续查询
- 基于 OpenAI Images 兼容协议，支持文生图 / 图生图
- 支持 13 种图片比例，通过 `size` 字段传入，平台会自动拼接到 prompt 交给上游
- 单次生成 1 张图片，参考图最多 16 张，支持 URL 与 base64 混填
- 提交的 prompt 会经过平台敏感词 / 安全审核，违规内容会被直接拒绝
- 生成结果由平台镜像到 R2 稳定链接，建议尽快下载或转存 

<RequestExample>
  ```bash cURL theme={null}
  curl --request POST \
    --url https://api.apimart.ai/v1/images/generations \
    --header 'Authorization: Bearer <token>' \
    --header 'Content-Type: application/json' \
    --data '{
      "model": "gpt-image-2",
      "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格",
      "n": 1,
      "size": "16:9"
    }'
  ```

  ```python Python theme={null}
  import requests

  url = "https://api.apimart.ai/v1/images/generations"

  payload = {
      "model": "gpt-image-2",
      "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格",
      "n": 1,
      "size": "16:9"
  }

  headers = {
      "Authorization": "Bearer <token>",
      "Content-Type": "application/json"
  }

  response = requests.post(url, json=payload, headers=headers)

  print(response.json())
  ```

  ```javascript JavaScript theme={null}
  const url = "https://api.apimart.ai/v1/images/generations";

  const payload = {
    model: "gpt-image-2",
    prompt: "一只橘猫坐在窗台上看夕阳，水彩画风格",
    n: 1,
    size: "16:9"
  };

  const headers = {
    "Authorization": "Bearer <token>",
    "Content-Type": "application/json"
  };

  fetch(url, {
    method: "POST",
    headers: headers,
    body: JSON.stringify(payload)
  })
    .then(response => response.json())
    .then(data => console.log(data))
    .catch(error => console.error('Error:', error));
  ```

  ```go Go theme={null}
  package main

  import (
      "bytes"
      "encoding/json"
      "fmt"
      "io/ioutil"
      "net/http"
  )

  func main() {
      url := "https://api.apimart.ai/v1/images/generations"

      payload := map[string]interface{}{
          "model":  "gpt-image-2",
          "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格",
          "n":      1,
          "size":   "16:9",
      }

      jsonData, _ := json.Marshal(payload)

      req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
      req.Header.Set("Authorization", "Bearer <token>")
      req.Header.Set("Content-Type", "application/json")

      client := &http.Client{}
      resp, err := client.Do(req)
      if err != nil {
          panic(err)
      }
      defer resp.Body.Close()

      body, _ := ioutil.ReadAll(resp.Body)
      fmt.Println(string(body))
  }
  ```

  ```java Java theme={null}
  import java.net.http.HttpClient;
  import java.net.http.HttpRequest;
  import java.net.http.HttpResponse;
  import java.net.URI;

  public class Main {
      public static void main(String[] args) throws Exception {
          String url = "https://api.apimart.ai/v1/images/generations";

          String payload = """
          {
            "model": "gpt-image-2",
            "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格",
            "n": 1,
            "size": "16:9"
          }
          """;

          HttpClient client = HttpClient.newHttpClient();
          HttpRequest request = HttpRequest.newBuilder()
              .uri(URI.create(url))
              .header("Authorization", "Bearer <token>")
              .header("Content-Type", "application/json")
              .POST(HttpRequest.BodyPublishers.ofString(payload))
              .build();

          HttpResponse<String> response = client.send(request,
              HttpResponse.BodyHandlers.ofString());

          System.out.println(response.body());
      }
  }
  ```

  ```php PHP theme={null}
  <?php

  $url = "https://api.apimart.ai/v1/images/generations";

  $payload = [
      "model" => "gpt-image-2",
      "prompt" => "一只橘猫坐在窗台上看夕阳，水彩画风格",
      "n" => 1,
      "size" => "16:9"
  ];

  $ch = curl_init($url);
  curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
  curl_setopt($ch, CURLOPT_POST, true);
  curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
  curl_setopt($ch, CURLOPT_HTTPHEADER, [
      "Authorization: Bearer <token>",
      "Content-Type: application/json"
  ]);

  $response = curl_exec($ch);
  curl_close($ch);

  echo $response;
  ?>
  ```

  ```ruby Ruby theme={null}
  require 'net/http'
  require 'json'
  require 'uri'

  url = URI("https://api.apimart.ai/v1/images/generations")

  payload = {
    model: "gpt-image-2",
    prompt: "一只橘猫坐在窗台上看夕阳，水彩画风格",
    n: 1,
    size: "16:9"
  }

  http = Net::HTTP.new(url.host, url.port)
  http.use_ssl = true

  request = Net::HTTP::Post.new(url)
  request["Authorization"] = "Bearer <token>"
  request["Content-Type"] = "application/json"
  request.body = payload.to_json

  response = http.request(request)
  puts response.body
  ```

  ```swift Swift theme={null}
  import Foundation

  let url = URL(string: "https://api.apimart.ai/v1/images/generations")!

  let payload: [String: Any] = [
      "model": "gpt-image-2",
      "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格",
      "n": 1,
      "size": "16:9"
  ]

  var request = URLRequest(url: url)
  request.httpMethod = "POST"
  request.setValue("Bearer <token>", forHTTPHeaderField: "Authorization")
  request.setValue("application/json", forHTTPHeaderField: "Content-Type")
  request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

  let task = URLSession.shared.dataTask(with: request) { data, response, error in
      if let error = error {
          print("Error: \(error)")
          return
      }

      if let data = data, let responseString = String(data: data, encoding: .utf8) {
          print(responseString)
      }
  }

  task.resume()
  ```

  ```csharp C# theme={null}
  using System;
  using System.Net.Http;
  using System.Text;
  using System.Threading.Tasks;

  class Program
  {
      static async Task Main(string[] args)
      {
          var url = "https://api.apimart.ai/v1/images/generations";

          var payload = @"{
              ""model"": ""gpt-image-2"",
              ""prompt"": ""一只橘猫坐在窗台上看夕阳，水彩画风格"",
              ""n"": 1,
              ""size"": ""16:9""
          }";

          using var client = new HttpClient();
          client.DefaultRequestHeaders.Add("Authorization", "Bearer <token>");

          var content = new StringContent(payload, Encoding.UTF8, "application/json");
          var response = await client.PostAsync(url, content);
          var result = await response.Content.ReadAsStringAsync();

          Console.WriteLine(result);
      }
  }
  ```

  ```dart Dart theme={null}
  import 'dart:convert';
  import 'package:http/http.dart' as http;

  void main() async {
    final url = Uri.parse('https://api.apimart.ai/v1/images/generations');

    final payload = {
      'model': 'gpt-image-2',
      'prompt': '一只橘猫坐在窗台上看夕阳，水彩画风格',
      'n': 1,
      'size': '16:9'
    };

    final response = await http.post(
      url,
      headers: {
        'Authorization': 'Bearer <token>',
        'Content-Type': 'application/json'
      },
      body: jsonEncode(payload),
    );

    print(response.body);
  }
  ```

  ```r R theme={null}
  library(httr)
  library(jsonlite)

  url <- "https://api.apimart.ai/v1/images/generations"

  payload <- list(
    model = "gpt-image-2",
    prompt = "一只橘猫坐在窗台上看夕阳，水彩画风格",
    n = 1,
    size = "16:9"
  )

  response <- POST(
    url,
    add_headers(
      Authorization = "Bearer <token>",
      `Content-Type` = "application/json"
    ),
    body = toJSON(payload, auto_unbox = TRUE),
    encode = "raw"
  )

  cat(content(response, "text"))
  ```
</RequestExample>

<ResponseExample>
  ```json 200 theme={null}
  {
    "code": 200,
    "data": [
      {
        "status": "submitted",
        "task_id": "task_01KPQ7J7DWB7QZ3WCEK3YVPBRA"
      }
    ]
  }
  ```

  ```json 400 theme={null}
  {
    "error": {
      "code": 400,
      "message": "prompt is required",
      "type": "invalid_request_error"
    }
  }
  ```

  ```json 401 theme={null}
  {
    "error": {
      "code": 401,
      "message": "身份验证失败，请检查您的API密钥",
      "type": "authentication_error"
    }
  }
  ```

  ```json 402 theme={null}
  {
    "error": {
      "code": 402,
      "message": "账户余额不足，请充值后再试",
      "type": "payment_required"
    }
  }
  ```

  ```json 403 theme={null}
  {
    "error": {
      "code": 403,
      "message": "访问被禁止，您没有权限访问此资源",
      "type": "permission_error"
    }
  }
  ```

  ```json 429 theme={null}
  {
    "error": {
      "code": 429,
      "message": "请求过于频繁，请稍后再试",
      "type": "rate_limit_error"
    }
  }
  ```

  ```json 500 build_request_failed theme={null}
  {
    "error": {
      "code": 500,
      "message": "build_request_failed: invalid size: 1024x1024, allowed: 1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 / 5:4 / 4:5 / 2:1 / 1:2 / 21:9 / 9:21",
      "type": "server_error"
    }
  }
  ```

  ```json 500 content_moderation theme={null}
  {
    "error": {
      "code": 500,
      "message": "build_request_failed: content moderation failed: sensitive content detected",
      "type": "server_error"
    }
  }
  ```

  ```json 502 theme={null}
  {
    "error": {
      "code": 502,
      "message": "网关错误，服务器暂时不可用",
      "type": "bad_gateway"
    }
  }
  ```
</ResponseExample>

## Authorizations

<ParamField header="Authorization" type="string" required>
  所有接口均需要使用 Bearer Token 进行认证

  获取 API Key：

  访问 [API Key 管理页面](https://apimart.ai/keys) 获取您的 API Key

  使用时在请求头中添加：

  ```
  Authorization: Bearer YOUR_API_KEY
  ```
</ParamField>

## Body

<ParamField body="model" type="string" default="gpt-image-2" required>
  图像生成模型名称

  固定填写 `gpt-image-2`
</ParamField>

<ParamField body="prompt" type="string" required>
  图像生成的文本描述

  * 支持中英文，建议详细描述
  * 提交前会经过平台敏感词 / 安全审核，命中违规内容会直接返回错误
</ParamField>

<ParamField body="n" type="integer" default="1">
  生成图片张数

  取值范围：`1`

  <Warning>
    必须传入纯数字（如 `1`），不要加引号
  </Warning>
</ParamField>

<ParamField body="size" type="string" default="1:1">
  图像生成的比例

  支持 13 种比例：

  * `1:1` - 正方形（默认）
  * `16:9` / `9:16` - 宽屏横 / 竖
  * `4:3` / `3:4` - 标屏横 / 竖
  * `3:2` / `2:3` - 经典横 / 竖
  * `5:4` / `4:5` - 近方横 / 竖
  * `2:1` / `1:2` - 宽横 / 长竖
  * `21:9` / `9:21` - 超宽横 / 超长竖

  <Warning>
    只支持比例写法。传 `1024x1024` 这种像素尺寸会直接报错 `build_request_failed: invalid size`
  </Warning>
</ParamField>

<ParamField body="image_urls" type="array">
  参考图数组（OpenAI 标准字段），传入后走图生图模式

  <Expandable title="详细说明">
    * 最多 16 张参考图，超过会返回 `image_urls exceeds max 16`
    * 支持 `图片 URL`（公网可访问的稳定链接）
    * 支持 `base64 data URI`（形如 `data:image/png;base64,...`）
    * 同一数组里可以 URL 与 base64 混填，服务端会自行处理
  </Expandable>
</ParamField>

<Note>
  其他 OpenAI 标准字段（如 `response_format`、`quality`、`style`）当前不支持，会被忽略。任务结果只返回 `url`，如需 base64 请自行下载转换。
</Note>

<ParamField body="official_fallback" type="boolean" default="false">
  是否使用官方渠道兜底

  * `false`：不使用（默认）
  * `true`：使用官方渠道
</ParamField>

## 使用场景示例

**文生图（最简请求）**

```json theme={null}
{
  "model": "gpt-image-2",
  "prompt": "一只橘猫坐在窗台上看夕阳，水彩画风格"
}
```

**文生图（指定比例）**

```json theme={null}
{
  "model": "gpt-image-2",
  "prompt": "a corgi astronaut on the moon, cinematic, 8k",
  "size": "16:9",
  "n": 1
}
```

**图生图（参考图 = URL）**

```json theme={null}
{
  "model": "gpt-image-2",
  "prompt": "把这张照片变成水彩画风格",
  "size": "1:1",
  "image_urls": [
    "https://example.com/photo.jpg"
  ]
}
```

**图生图（参考图 = base64）**

```json theme={null}
{
  "model": "gpt-image-2",
  "prompt": "把这张照片变成水彩画风格",
  "image_urls": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

**图生图（多参考图融合，URL + base64 混填）**

```json theme={null}
{
  "model": "gpt-image-2",
  "prompt": "把这两张照片融合成一张海报",
  "size": "4:3",
  "image_urls": [
    "https://example.com/photo-a.jpg",
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

## Response

<ResponseField name="code" type="integer">
  响应状态码
</ResponseField>

<ResponseField name="data" type="array">
  返回数据数组

  <Expandable title="属性">
    <ResponseField name="status" type="string">
      任务状态

      * `submitted` - 已提交
    </ResponseField>

    <ResponseField name="task_id" type="string">
      任务唯一标识符，用于后续查询任务结果
    </ResponseField>
  </Expandable>
</ResponseField>

## 查询任务结果

提交成功后返回 `task_id`，通过 `GET /v1/tasks/{task_id}` 轮询任务状态，详见 [任务查询接口](/cn/api-reference/tasks/get-task)。

### 成功响应示例

```json theme={null}
{
  "code": 200,
  "data": {
    "id": "task_01KPQ7J7DWB7QZ3WCEK3YVPBRA",
    "status": "completed",
    "progress": 100,
    "created": 1776748674,
    "completed": 1776748726,
    "actual_time": 52,
    "estimated_time": 100,
    "result": {
      "images": [
        {
          "url": [
            "https://upload.apimart.ai/f/image/xxxxxxxx-gpt_image_2_task_xxx_0.png"
          ],
          "expires_at": 1776835126
        }
      ]
    }
  }
}
```

取图方式：`data.result.images[0].url[0]`

### 任务状态说明

| 状态           | 含义                    |
| ------------ | --------------------- |
| `pending`    | 已提交 / 排队中             |
| `processing` | 上游处理中                 |
| `completed`  | 成功，`result.images` 可用 |
| `failed`     | 失败，查看 `error.message` |

### 轮询建议

* **首次查询延迟**：提交后等待 10\~20 秒再开始查询
* **查询间隔**：建议 3\~5 秒一次，避免无脑毫秒级轮询
* **超时参考**：单张图一般 30~~60 秒完成（实测 `actual_time` 44~~52s）
* **批量查询**：若需同时查询多个任务，请使用 `POST /v1/tasks/batch`，请求体 `{"task_ids": ["task_xxx", "task_yyy"]}`

## 注意事项

1. **异步处理**：提交后返回 `task_id`，需轮询 `/v1/tasks/{task_id}` 获取最终图片 URL
2. **内容审核**：`prompt` 会先经过平台敏感词 / 安全审核，命中违规内容会直接拒绝并不会计费
3. **结果 URL**：平台已将上游临时签名链接镜像到自家 R2 对象存储，返回的是稳定链接，客户端可直接访问
4. **URL 时效**：响应中的 `expires_at = completed + 24h` 是业务层提示字段，建议尽快下载或转存到自己的 CDN
5. **比例冲突**：推荐只通过 `size` 字段传比例，不要在 `prompt` 里重复写比例，避免上游理解冲突
6. **计费规则**：按张计费，失败不扣费，审核未通过不扣费
7. **任务保留**：`task_id` 在数据库里默认保留若干天（由 `TASK_RETENTION_DAYS` 配置），过期后查询会返回"任务不存在或已过期"

---

> ## Documentation Index
> Fetch the complete documentation index at: https://docs.apimart.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# doubao-seedance-2.0 视频生成

>  - 异步处理模式，返回任务ID用于后续查询
- 支持文生视频、图生视频（首帧/尾帧）
- 支持参考视频、参考音频、有声视频
- 支持横屏、竖屏、方形、超宽屏、自适应多种比例 

<RequestExample>
  ```bash cURL theme={null}
  curl --request POST \
    --url https://api.apimart.ai/v1/videos/generations \
    --header 'Authorization: Bearer <token>' \
    --header 'Content-Type: application/json' \
    --data '{
      "model": "doubao-seedance-2.0",
      "prompt": "小猫对着镜头打哈欠",
      "resolution": "720p",
      "size": "16:9",
      "duration": 5,
      "generate_audio": true
    }'
  ```

  ```python Python theme={null}
  import requests

  url = "https://api.apimart.ai/v1/videos/generations"

  payload = {
      "model": "doubao-seedance-2.0",
      "prompt": "小猫对着镜头打哈欠",
      "resolution": "720p",
      "size": "16:9",
      "duration": 5,
      "generate_audio": True
  }

  headers = {
      "Authorization": "Bearer <token>",
      "Content-Type": "application/json"
  }

  response = requests.post(url, json=payload, headers=headers)

  print(response.json())
  ```

  ```javascript JavaScript theme={null}
  const url = "https://api.apimart.ai/v1/videos/generations";

  const payload = {
    model: "doubao-seedance-2.0",
    prompt: "小猫对着镜头打哈欠",
    resolution: "720p",
    size: "16:9",
    duration: 5,
    generate_audio: true
  };

  const headers = {
    "Authorization": "Bearer <token>",
    "Content-Type": "application/json"
  };

  fetch(url, {
    method: "POST",
    headers: headers,
    body: JSON.stringify(payload)
  })
    .then(response => response.json())
    .then(data => console.log(data))
    .catch(error => console.error('Error:', error));
  ```

  ```go Go theme={null}
  package main

  import (
      "bytes"
      "encoding/json"
      "fmt"
      "io/ioutil"
      "net/http"
  )

  func main() {
      url := "https://api.apimart.ai/v1/videos/generations"

      payload := map[string]interface{}{
          "model":          "doubao-seedance-2.0",
          "prompt":         "小猫对着镜头打哈欠",
          "resolution":     "720p",
          "size":           "16:9",
          "duration":       5,
          "generate_audio": true,
      }

      jsonData, _ := json.Marshal(payload)

      req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
      req.Header.Set("Authorization", "Bearer <token>")
      req.Header.Set("Content-Type", "application/json")

      client := &http.Client{}
      resp, err := client.Do(req)
      if err != nil {
          panic(err)
      }
      defer resp.Body.Close()

      body, _ := ioutil.ReadAll(resp.Body)
      fmt.Println(string(body))
  }
  ```

  ```java Java theme={null}
  import java.net.http.HttpClient;
  import java.net.http.HttpRequest;
  import java.net.http.HttpResponse;
  import java.net.URI;

  public class Main {
      public static void main(String[] args) throws Exception {
          String url = "https://api.apimart.ai/v1/videos/generations";

          String payload = """
          {
            "model": "doubao-seedance-2.0",
            "prompt": "小猫对着镜头打哈欠",
            "resolution": "720p",
            "size": "16:9",
            "duration": 5,
            "generate_audio": true
          }
          """;

          HttpClient client = HttpClient.newHttpClient();
          HttpRequest request = HttpRequest.newBuilder()
              .uri(URI.create(url))
              .header("Authorization", "Bearer <token>")
              .header("Content-Type", "application/json")
              .POST(HttpRequest.BodyPublishers.ofString(payload))
              .build();

          HttpResponse<String> response = client.send(request,
              HttpResponse.BodyHandlers.ofString());

          System.out.println(response.body());
      }
  }
  ```

  ```php PHP theme={null}
  <?php

  $url = "https://api.apimart.ai/v1/videos/generations";

  $payload = [
      "model" => "doubao-seedance-2.0",
      "prompt" => "小猫对着镜头打哈欠",
      "resolution" => "720p",
      "size" => "16:9",
      "duration" => 5,
      "generate_audio" => true
  ];

  $ch = curl_init($url);
  curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
  curl_setopt($ch, CURLOPT_POST, true);
  curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
  curl_setopt($ch, CURLOPT_HTTPHEADER, [
      "Authorization: Bearer <token>",
      "Content-Type: application/json"
  ]);

  $response = curl_exec($ch);
  curl_close($ch);

  echo $response;
  ?>
  ```

  ```ruby Ruby theme={null}
  require 'net/http'
  require 'json'
  require 'uri'

  url = URI("https://api.apimart.ai/v1/videos/generations")

  payload = {
    model: "doubao-seedance-2.0",
    prompt: "小猫对着镜头打哈欠",
    resolution: "720p",
    size: "16:9",
    duration: 5,
    generate_audio: true
  }

  http = Net::HTTP.new(url.host, url.port)
  http.use_ssl = true

  request = Net::HTTP::Post.new(url)
  request["Authorization"] = "Bearer <token>"
  request["Content-Type"] = "application/json"
  request.body = payload.to_json

  response = http.request(request)
  puts response.body
  ```

  ```swift Swift theme={null}
  import Foundation

  let url = URL(string: "https://api.apimart.ai/v1/videos/generations")!

  let payload: [String: Any] = [
      "model": "doubao-seedance-2.0",
      "prompt": "小猫对着镜头打哈欠",
      "resolution": "720p",
      "size": "16:9",
      "duration": 5,
      "generate_audio": true
  ]

  var request = URLRequest(url: url)
  request.httpMethod = "POST"
  request.setValue("Bearer <token>", forHTTPHeaderField: "Authorization")
  request.setValue("application/json", forHTTPHeaderField: "Content-Type")
  request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

  let task = URLSession.shared.dataTask(with: request) { data, response, error in
      if let error = error {
          print("Error: \(error)")
          return
      }

      if let data = data, let responseString = String(data: data, encoding: .utf8) {
          print(responseString)
      }
  }

  task.resume()
  ```

  ```csharp C# theme={null}
  using System;
  using System.Net.Http;
  using System.Text;
  using System.Threading.Tasks;

  class Program
  {
      static async Task Main(string[] args)
      {
          var url = "https://api.apimart.ai/v1/videos/generations";

          var payload = @"{
              ""model"": ""doubao-seedance-2.0"",
              ""prompt"": ""小猫对着镜头打哈欠"",
              ""resolution"": ""720p"",
              ""size"": ""16:9"",
              ""duration"": 5,
              ""generate_audio"": true
          }";

          using var client = new HttpClient();
          client.DefaultRequestHeaders.Add("Authorization", "Bearer <token>");

          var content = new StringContent(payload, Encoding.UTF8, "application/json");
          var response = await client.PostAsync(url, content);
          var result = await response.Content.ReadAsStringAsync();

          Console.WriteLine(result);
      }
  }
  ```
</RequestExample>

<ResponseExample>
  ```json 200 theme={null}
  {
    "code": 200,
    "data": [
      {
        "status": "submitted",
        "task_id": "task_01KMCGF6BQGN3X28H3KSR50X5T"
      }
    ]
  }
  ```

  ```json 400 theme={null}
  {
    "error": {
      "code": 400,
      "message": "请求参数无效",
      "type": "invalid_request_error"
    }
  }
  ```

  ```json 401 theme={null}
  {
    "error": {
      "code": 401,
      "message": "身份验证失败，请检查您的API密钥",
      "type": "authentication_error"
    }
  }
  ```

  ```json 402 theme={null}
  {
    "error": {
      "code": 402,
      "message": "账户余额不足，请充值后再试",
      "type": "payment_required"
    }
  }
  ```

  ```json 429 theme={null}
  {
    "error": {
      "code": 429,
      "message": "请求过于频繁，请稍后再试",
      "type": "rate_limit_error"
    }
  }
  ```

  ```json 500 theme={null}
  {
    "error": {
      "code": 500,
      "message": "服务器内部错误，请稍后重试",
      "type": "server_error"
    }
  }
  ```
</ResponseExample>

## 认证

<ParamField header="Authorization" type="string" required>
  所有接口均需要使用 Bearer Token 进行认证

  获取 API Key：

  访问 [API Key 管理页面](https://apimart.ai/keys) 获取您的 API Key

  使用时在请求头中添加：

  ```
  Authorization: Bearer YOUR_API_KEY
  ```
</ParamField>

## 请求参数

<ParamField body="model" type="string" required>
  视频生成模型名称

  支持的模型：

  * `doubao-seedance-2.0` - 标准版，支持文生视频、图生视频、首尾帧视频、参考视频、参考音频、有声视频
  * `doubao-seedance-2.0-fast` - 快速版，功能与标准版一致，生成速度更快
  * `doubao-seedance-2.0-face` - 支持上传真人版，功能与标准版一致
  * `doubao-seedance-2.0-fast-face` - 支持上传真人版，功能与快速版一致
</ParamField>

<ParamField body="prompt" type="string">
  视频内容描述

  文生视频时必填，图生视频/视频参考生视频时可选

  建议明确主体、动作、镜头和风格，以获得更好的生成效果

  示例：`"小猫对着镜头打哈欠"`
</ParamField>

<ParamField body="duration" type="integer" default="5">
  视频时长（秒）

  支持范围：`4` \~ `15` 秒

  默认值：`5`
</ParamField>

<ParamField body="size" type="string" default="16:9">
  视频宽高比

  可选值：

  * `16:9` - 横屏
  * `9:16` - 竖屏
  * `1:1` - 方形
  * `4:3` - 传统比例
  * `3:4` - 竖向传统比例
  * `21:9` - 超宽屏
  * `adaptive` - 自适应（根据输入图片/视频自动匹配）

  默认值：`16:9`
</ParamField>

<ParamField body="resolution" type="string" default="480p">
  视频分辨率

  可选值：

  * `480p` - 标清
  * `720p` - 高清
  * `1080p` - 全高清（仅 `doubao-seedance-2.0-face` 支持）

  默认值：`480p`
</ParamField>

<ParamField body="seed" type="integer">
  随机种子，用于控制生成内容的随机性

  <Note>
    * 相同的请求下，模型收到不同的 seed 值，将生成不同的结果
    * 相同的请求下，模型收到相同的 seed 值，会生成类似的结果，但不保证完全一致
  </Note>
</ParamField>

<ParamField body="generate_audio" type="boolean" default="false">
  是否生成音频（有声视频）

  设置为 `true` 时，视频将包含 AI 生成的配套音频

  默认值：`false`
</ParamField>

<ParamField body="return_last_frame" type="boolean" default="false">
  是否返回尾帧图片

  设置为 `true` 时，任务结果中会额外返回视频最后一帧的图片 URL，可用于连续视频生成

  默认值：`false`
</ParamField>

<ParamField body="tools" type="array<object>">
  工具列表，用于联网搜索等增强能力

  示例：`[{"type": "web_search"}]`

  <Expandable title="字段说明">
    <ParamField body="type" type="string" required>
      工具类型

      可选值：

      * `web_search` - 联网搜索，生成时参考网络信息
    </ParamField>
  </Expandable>
</ParamField>

<ParamField body="image_urls" type="array<string>">
  图片 URL 数组，用于图生视频

  示例：`["https://example.com/cat.jpg"]`

  <Warning>
    * `image_urls` 和 `image_with_roles` 不能同时使用
    * 最多 9 张参考图
  </Warning>
</ParamField>

<ParamField body="image_with_roles" type="array">
  带角色的图片数组，支持指定首帧/尾帧

  <Expandable title="字段说明">
    <ParamField body="url" type="string" required>
      图片 URL 地址
    </ParamField>

    <ParamField body="role" type="string" required>
      图片角色

      可选值：

      * `first_frame` - 首帧图，作为视频起始画面
      * `last_frame` - 尾帧图，作为视频结束画面
    </ParamField>
  </Expandable>

  示例：

  ```json theme={null}
  [
    {"url": "https://example.com/day.jpg", "role": "first_frame"},
    {"url": "https://example.com/night.jpg", "role": "last_frame"}
  ]
  ```

  <Warning>
    * `image_urls` 和 `image_with_roles` 不能同时使用
    * 使用首尾帧图片时，`video_urls` 和 `audio_urls` 不可用
  </Warning>
</ParamField>

<ParamField body="video_urls" type="array<string>">
  参考视频 URL 数组

  需要可公网访问的视频 URL

  示例：`["https://example.com/reference.mp4"]`

  <Warning>
    * 使用首帧/尾帧图片（`image_with_roles`）时，参考视频不可用
    * 最多 3 个参考视频，总时长 ≤ 15s
    * 参考视频分辨率需要在 480P \~ 720P 之间
    * 参考视频不可出现真人
  </Warning>
</ParamField>

<ParamField body="audio_urls" type="array<string>">
  参考音频 URL 数组

  需要可公网访问的音频 URL

  示例：`["https://example.com/speech.wav"]`

  <Warning>
    * 使用首帧/尾帧图片（`image_with_roles`）时，参考音频不可用
    * 最多 3 个参考音频，总时长 ≤ 15s
    * 参考音频需与参考图片或者参考视频使用
  </Warning>
</ParamField>

## 响应

<ResponseField name="code" type="integer">
  响应状态码，成功时为 200
</ResponseField>

<ResponseField name="data" type="array">
  返回数据数组

  <Expandable title="数组元素">
    <ResponseField name="status" type="string">
      任务状态，初始提交时为 `submitted`
    </ResponseField>

    <ResponseField name="task_id" type="string">
      任务唯一标识符，用于查询任务状态和结果
    </ResponseField>
  </Expandable>
</ResponseField>

## 使用场景

### 场景 1：文生视频

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "小猫对着镜头打哈欠",
  "resolution": "720p",
  "size": "16:9",
  "duration": 5,
  "seed": 42,
  "generate_audio": true
}
```

### 场景 2：图生视频（首帧）

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "小猫站起来走向镜头",
  "image_urls": ["https://example.com/cat.jpg"],
  "duration": 5
}
```

### 场景 3：首尾帧视频

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "从白天过渡到夜晚",
  "image_with_roles": [
    {"url": "https://example.com/day.jpg", "role": "first_frame"},
    {"url": "https://example.com/night.jpg", "role": "last_frame"}
  ],
  "duration": 5
}
```

### 场景 4：视频参考生视频

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "将视频风格转换为动漫风格",
  "video_urls": ["https://example.com/reference.mp4"]
}
```

### 场景 5：参考视频 + 参考音频

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "人物说话的场景",
  "video_urls": ["https://example.com/reference.mp4"],
  "audio_urls": ["https://example.com/speech.wav"],
  "size": "16:9",
  "duration": 11
}
```

### 场景 6：有声视频

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "男人叫住女人说：\"你记住，以后不可以用手指指月亮。\"",
  "generate_audio": true
}
```

### 场景 7：连续视频生成（返回尾帧）

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "小猫继续走向镜头",
  "image_urls": ["https://example.com/last_frame_from_prev.png"],
  "return_last_frame": true
}
```

### 场景 8：快速版生成

```json theme={null}
{
  "model": "doubao-seedance-2.0-fast",
  "prompt": "城市夜景延时摄影",
  "size": "21:9",
  "duration": 8
}
```

### 场景 9：参考图片 + 参考视频 + 参考音频（多模态视频）

结合参考图片、参考视频和参考音频，生成沉浸式第一人称视角广告视频。适用于产品宣传、品牌广告等需要多素材融合的场景。

```json theme={null}
{
  "model": "doubao-seedance-2.0",
  "prompt": "全程使用视频1的第一视角构图，全程使用音频1作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为图片1，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；4-6秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；6-8秒：第一人称手持举杯，你将图片2中的果茶举到镜头前（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，尾帧定格为图片2。背景声音统一为女生音色。",
  "image_urls": [
    "https://example.com/tea_pic1.jpg",
    "https://example.com/tea_pic2.jpg"
  ],
  "video_urls": ["https://example.com/tea_video1.mp4"],
  "audio_urls": ["https://example.com/tea_audio1.mp3"],
  "generate_audio": true,
  "size": "16:9",
  "duration": 11
}
```

<Note>
  **查询任务结果**

  视频生成为异步任务，提交后会返回 `task_id`。使用 [获取任务状态](/cn/api-reference/tasks/status) 接口查询生成进度和结果。
</Note>

## 与 1.5 Pro 版本的差异

| 特性    | 1.5 Pro                           | 2.0 / 2.0 fast                        |
| ----- | --------------------------------- | ------------------------------------- |
| 分辨率   | 480p/720p/1080p                   | **480p/720p**                         |
| 时长范围  | 4-12秒                             | **5-15秒**                             |
| 默认时长  | 5秒                                | **5秒**                                |
| 宽高比参数 | `aspect_ratio`                    | **`size`**（新增 `adaptive` 自适应）         |
| 音频生成  | `audio` 参数                        | **`generate_audio` 参数**               |
| 参考视频  | 不支持                               | **支持 `video_urls`**                   |
| 参考音频  | 不支持                               | **支持 `audio_urls`**                   |
| 图生视频  | `image_urls` / `image_with_roles` | **`image_urls` / `image_with_roles`** |
| 有声视频  | 不支持                               | **支持 `generate_audio`**               |
| 连续视频  | 不支持                               | **支持 `return_last_frame`**            |
| 快速版   | 不支持                               | **支持 `doubao-seedance-2.0-fast`**     |
