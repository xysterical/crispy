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


# Kimi K2.6 对图片与视频的理解

> Fetch the complete documentation index at: https://platform.kimi.com/docs/llms.txt

## Kimi K2.6 模型介绍

Kimi K2.6 是 Kimi 最新最智能的模型，Kimi K2.6 的通用 Agent、代码、视觉理解等综合能力得到全面提升，其中在博士级难度的完整版人类最后的考试（Humanity's Last Exam）、在考察模型真实软件工程能力的 SWE-Bench Pro、评估 Agent 深度检索能力的 DeepSearchQA 等基准测试中均取得行业领先的成绩，同时支持文本、图片与视频输入，思考与非思考模式，对话与 Agent 任务。

### 长程编码能力突破

* Kimi K2.6 作为国内领先的 Coding 模型，在长程代码任务中的表现取得了突破，面对不同编程语言（如 Rust、Go、Python）和任务场景（如前端、运维、性能优化）均具备更可靠的泛化能力。

### 超长上下文支持

* `kimi-k2.6`、`kimi-k2.5`、`kimi-k2-0905-preview`、`kimi-k2-turbo-preview`、`kimi-k2-thinking`、`kimi-k2-thinking-turbo` 模型均提供 256K 上下文窗口

### 长思考能力

* Kimi K2.6 仍然具备超强的思考能力，支持多步工具调用和推理，擅长解决复杂问题，如复杂的逻辑推理、数学问题、代码编写等。

## 立即开始

* [立即体验](https://platform.kimi.com/playground)：在开发工作台，快速通过交互式操作测试模型在业务场景上的效果
* [申请 API Key](https://platform.kimi.com/console/api-keys)：立即通过 API 调用测试

## 调用示例

以下是完整的调用示例，帮助您快速上手 Kimi K2.6 多模态模型。

### 安装 OpenAI SDK

Kimi API 完全兼容 OpenAI 的 API 格式，你可以通过如下方式来安装 OpenAI SDK：

```python theme={null}
pip install --upgrade 'openai>=1.0'
```

### 验证安装结果

```python theme={null}
python -c 'import openai; print("version =",openai.__version__)'

# 输出可能是 version = 1.10.0，表示 OpenAI SDK 已经安装成功，当前 python 实际使用了 openai 的 v1.10.0 的库

```

### 图片理解代码示例

```python theme={null}
import os
import base64

from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY"),
    base_url="https://api.moonshot.cn/v1",
)

# 在这里，你需要将 kimi.png 文件替换为你想让 Kimi 识别的图片的地址
image_path = "kimi.png"

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

```

### 视频理解代码示例

```python theme={null}
import os
import base64

from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY"),
    base_url="https://api.moonshot.cn/v1",
)

# 在这里，你需要将 kimi.mp4 文件替换为你想让 Kimi 识别的视频的地址
video_path = "kimi.mp4"

with open(video_path, "rb") as f:
    video_data = f.read()

# 我们使用标准库 base64.b64encode 函数将视频编码成 base64 格式的 video_url
video_url = f"data:video/{os.path.splitext(video_path)[1].lstrip('.')};base64,{base64.b64encode(video_data).decode('utf-8')}"


completion = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "system", "content": "你是 Kimi。"},
        {
            "role": "user",
            # 注意这里，content 由原来的 str 类型变更为一个 list，这个 list 中包含多个部分的内容，视频（video_url）是一个部分（part），
            # 文字（text）是一个部分（part）
            "content": [
                {
                    "type": "video_url", # <-- 使用 video_url 类型来上传视频，内容为使用 base64 编码过的视频内容
                    "video_url": {
                        "url": video_url,
                    },
                },
                {
                    "type": "text",
                    "text": "请描述视频的内容。", # <-- 使用 text 类型来提供文字指令，例如"描述视频内容"
                },
            ],
        },
    ],
)

print(completion.choices[0].message.content)

```

### 多模态工具能力示例

Kimi K2.6 模型综合了多种能力。以下是一个展示 K2.6 视觉理解+工具调用能力的示例。

首先将这个示例视频下载到本地，比如 `/path/to/test_video.mp4`

<Frame>
  <video controls style={{ width: '100%', height: 'auto' }}>
    <source src="https://mintcdn.com/moonshotcn/7u71GHTjBBTV0Hno/assets/pics/test_video.mp4?fit=max&auto=format&n=7u71GHTjBBTV0Hno&q=85&s=b34c03e178057982b8305867f46043eb" type="video/mp4" data-path="assets/pics/test_video.mp4" />
  </video>
</Frame>

然后运行以下代码

```python theme={null}
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from openai import OpenAI

tools = [{
    "type": "function",
    "function": {
        "name": "watch_video_clip",
        "description": "Watch a video file or a sub-clip of it. If start_time and end_time are not provided, the entire video will be returned.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the video file to watch"
                },
                "start_time": {
                    "type": "number",
                    "description": "The start time of the clip in seconds (optional, defaults to 0)"
                },
                "end_time": {
                    "type": "number",
                    "description": "The end time of the clip in seconds (optional, defaults to end of video)"
                }
            },
            "required": ["path"]
        }
    }
}]

def watch_video_clip(path: str, start_time: float | None = None, end_time: float | None = None) -> list[dict]:
    """
    Watch a video file or a sub-clip of it.

    Args:
        path: The path to the video file to watch
        start_time: The start time in seconds (optional, defaults to 0)
        end_time: The end time in seconds (optional, defaults to end of video)

    Returns:
        A list of content blocks in MultiModal Tool API format
    """

    video_path = Path(path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")

    # Get video duration if needed
    if start_time is None and end_time is None:
        # Return entire video
        with open(path, "rb") as f:
            video_base64 = base64.b64encode(f.read()).decode("utf-8")
        return [
            {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_base64}"}},
            {"type": "text", "text": f"Full video: {video_path.name}"}
        ]

    # Get video duration for defaults
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])

    start_time = start_time or 0
    end_time = end_time or duration
    clip_duration = end_time - start_time

    # Extract clip
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start_time), "-i", path,
            "-t", str(clip_duration), "-c:v", "libx264", "-c:a", "aac",
            "-preset", "fast", "-crf", "23", "-movflags", "+faststart",
            "-loglevel", "error", tmp_path
        ], check=True)

        with open(tmp_path, "rb") as f:
            video_base64 = base64.b64encode(f.read()).decode("utf-8")

        return [
            {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_base64}"}},
            {"type": "text", "text": f"Clip from {video_path.name}: {start_time}s - {end_time}s"}
        ]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY"),
    base_url="https://api.moonshot.cn/v1"
)

def agent_loop(user_message: str):
    """Simple agent loop with multimodal tool support."""

    messages = [
        {"role": "system", "content": "You are a video analysis assistant. Use watch_video_clip to examine specific portions of videos."},
        {"role": "user", "content": user_message}
    ]

    while True:
        response = client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        message = response.choices[0].message
        messages.append(message.model_dump())

        # No tool calls = done
        if not message.tool_calls:
            return message.content

        # Execute tool calls
        for tool_call in message.tool_calls:
            if tool_call.function.name == "watch_video_clip":
                args = json.loads(tool_call.function.arguments)
                result = watch_video_clip(
                    path=args["path"],
                    start_time=args.get("start_time"),
                    end_time=args.get("end_time")
                )
                # Multimodal tool result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

# Usage
answer = agent_loop("分析 /path/to/test_video.mp4 这个视频的 8-13 秒发生了什么")
print(answer)
```

## 最佳实践

### 支持的格式

图片支持 png、jpeg、webp、gif；视频支持 mp4、mpeg、mov、avi、x-flv、mpg、webm、wmv、3gpp 格式。

### Tokens 计算及费用

图片与视频进行动态token计算，可以通过 [计算token接口](/api/estimate) ，在开始理解前获取包含图片或视频的请求的token消耗。

一般说来，图片分辨率越高，消耗的token越多；视频由若干张关键帧组成，关键帧的数量越多，分辨率越高，则token消耗越多。

Vision 模型在计费方式上与 `moonshot-v1` 系列模型保持一致，根据模型推理的总 Tokens 计费，详情请查看：

关于token价格，详见 [模型推理价格说明](/pricing/chat-k26)

### 分辨率说明

我们推荐图片分辨率不超过4k (4096\*2160)，视频分辨率不超过2k (2048\*1080)，再高的分辨率只会增加处理时间，也不会对模型理解的效果有提升。

### 上传文件还是base64

由于我们对请求体的整体大小有限制，所以对于非常大的视频，必须使用上传文件的方式使用视觉理解功能。对于需要多次引用的图片或视频，我们推荐使用文件上传的方式使用视觉理解功能。关于上传文件的限制，请参阅 [文件上传](/api/files-upload) 文档。

图片数量限制：Vision 模型没有图片数量限制，但请确保请求的 Body 大小不超过 100M

URL 格式的图片：不支持，目前仅支持使用 base64 编码的图片内容

## 参数变动说明

在 [chat](/api/chat) 文档中有一系列参数，但对于 K2.6/K2.5系列模型，其行为会有所不同。

**我们建议用户不要手动设置这些字段，而是使用默认值**

参数变动列举如下

| 字段                 | 是否必须     | 说明                    | 类型     | 取值                                                                            |
| ------------------ | -------- | --------------------- | ------ | ----------------------------------------------------------------------------- |
| max\_tokens        | optional | 聊天完成时生成的最大 token 数。   | int    | 默认值为32k，即32768                                                                |
| thinking           | optional | **新增** 该参数控制模型是否启用思考。 | object | 默认值为`{"type": "enabled"}`. 只能为 `{"type": "enabled"}` 或 `{"type": "disabled"}` |
| temperature        | optional | 使用什么采样温度。             | float  | k2.6/k2.5 系列模型将使用确定值 1.0, 非思考模式下将使用确认值 0.6。若指定其他值，将会报错。                       |
| top\_p             | optional | 采样方法。                 | float  | k2.6/k2.5 系列模型将使用确定值 0.95。若指定其他值，将会报错。                                        |
| n                  | optional | 为每条输入消息生成多少个结果。       | int    | k2.6/k2.5 系列模型将使用确定值 1。若指定其他值，将会报错。                                           |
| presence\_penalty  | optional | 存在惩罚。                 | float  | k2.6/k2.5 系列模型将使用固定值 0.0。 若指定其他值，将会报错。                                        |
| frequency\_penalty | optional | 频率惩罚。                 | float  | k2.6/k2.5 系列模型将使用确定值 0.0。若指定其他值，将会报错。                                         |

## Tool Use 参数兼容性

当使用工具时，若thinking设置值为`{"type": "enabled"}`，请注意，为了确保模型的性能，会有以下约束：

* 为了避免思考内容与指定的 `tool_choice` 冲突，`tool_choice` 只能使用"auto"和"none"（默认值为"auto"），取任何其他值将会报错；
* 在多步工具调用过程中，您必须在将本轮会话中工具调用时assistant message里的 `reasoning_content` 保留在上下文当中，否则会报错；
* 官方内置的 builtin 的联网搜索 `$web_search` 工具暂时与 Kimi K2.6/Kimi K2.5思考模式不兼容，可以选择先关闭思考模式后使用联网搜索工具 `$web_search`。

您可以参考[如何使用思考模型](/guide/use-kimi-k2-thinking-model)正确使用工具调用。

### K2.6 禁用思考能力示例

对于 `kimi-k2.6`, `kimi-k2.5` 模型，提供禁用思考能力的选项，需要在请求体中指定 `"thinking": {"type": "disabled"}`：

<Tabs>
  <Tab title="curl">
    ```bash theme={null}
    $ curl https://api.moonshot.cn/v1/chat/completions \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $MOONSHOT_API_KEY" \
        -d '{
            "model": "kimi-k2.6",
            "messages": [
                {"role": "user", "content": "你好"}
            ],
            "thinking": {"type": "disabled"}
       }'
    ```
  </Tab>

  <Tab title="python">
    ```python theme={null}
    import os
    import openai

    client = openai.Client(
        base_url="https://api.moonshot.cn/v1",
        api_key=os.getenv("MOONSHOT_API_KEY"),
    )

    response = client.chat.completions.create(
        model="kimi-k2.6",
        messages=[
            {"role": "user", "content": "你好"}
        ],
        extra_body={
            "thinking": {"type": "disabled"}
        },  # 通过 extra_body 参数，传递额外请求体，从而禁用思考能力
        max_tokens=1024*32
        # 无需设置temperature
    )

    print(response.choices[0].message.content)
    print(response)
    ```
  </Tab>
</Tabs>

## 模型价格

关于token价格，详见 [模型推理价格说明](/pricing/chat-k26)

## 了解更多

* 使用 Kimi 模型进行基准测试，请参考这篇 [基准测试最佳实践](/guide/benchmark-best-practice)
* Kimi K2.6 的最详细的 API 使用示例请见：[使用 Kimi 视觉模型](/guide/use-kimi-vision-model)
* 在这里查看在 [Claude Code, Roo Code, Cline中使用 Kimi模型](/guide/agent-support)的方法
* 在这里查看如何配置使用[思考模型](/guide/use-kimi-k2-thinking-model)
* 联网搜索是Kimi API官方提供的强大工具之一，在这里查看如何使用[联网搜索](/guide/use-web-search)，以及其他[官方工具](/guide/use-official-tools)
* 在这里查看全部[模型价格](/pricing/chat)，[充值与限速说明](/pricing/limits)，[联网搜索价格说明](/pricing/tools)
