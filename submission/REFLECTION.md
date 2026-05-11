# Day 23 Lab Reflection

**Student:** Lưu Linh Ly
**Submission date:** 2026-05-11  
**Lab repo URL:** (https://github.com/darlinhlyluu/Day23-Track2-Observability-Lab)

---

## 1. Hardware + setup output

Kết quả chạy `python 00-setup/verify-docker.py`:

```json
{
  "docker": {"ok": true, "version": "29.4.0"},
  "compose_v2": {"ok": true, "version": "5.1.1"},
  "ram_gb_available": 3.71,
  "ram_ok": false,
  "required_ports": [8000, 9090, 9093, 3000, 3100, 16686, 4317, 4318, 8888],
  "bound_ports": [],
  "all_ports_free": true
}
```

Mình dùng Docker Desktop trên Windows để chạy lab. Docker và Docker Compose v2 đều hoạt động đúng, các port cần thiết đều trống. Cảnh báo duy nhất là Docker Desktop hiện cấp khoảng 3.71 GB RAM, thấp hơn mức khuyến nghị 4 GB của lab. Stack vẫn chạy được, nhưng nếu dùng lâu hơn hoặc chạy thêm bonus thì mình sẽ tăng memory của Docker Desktop lên 6-8 GB để Grafana, Loki và Jaeger ổn định hơn.

---

## 2. Track 02 - Dashboards & Alerts

Stack đã provision dashboard tự động bằng Grafana dashboards-as-code. Các dashboard chính gồm AI Service Overview, SLO Burn Rate, Cost & Tokens và Cross-Day Stack. Sau khi tạo traffic vào endpoint `/predict`, Prometheus scrape được các metric RED/USE và AI-specific:

- `inference_requests_total`
- `inference_latency_seconds_bucket`
- `inference_active_gauge`
- `gpu_utilization_percent`
- `inference_tokens_total`
- `inference_quality_score`

Ảnh `submission/screenshots/dashboard-overview.png` cho thấy 6 panel overview có dữ liệu: request rate, latency, error rate, GPU utilization, token throughput và in-flight requests. Ảnh `submission/screenshots/cost-and-tokens.png` cho thấy token throughput và estimated cost khác 0. Ảnh `submission/screenshots/slo-burn-rate.png` cho thấy error budget và burn-rate đã populate sau khi có traffic lỗi.

Với phần alert, giảng viên cho phép dùng Discord thay Slack. Alertmanager gửi alert qua một Discord bridge nhỏ, bridge chuyển payload Alertmanager thành message Discord plain text. Evidence đã được chụp ở:

- `submission/screenshots/alertmanager-firing.png`
- `submission/screenshots/slack-firing.png`
- `submission/screenshots/slack-resolved.png`

Điều làm mình bất ngờ ở Prometheus/Grafana là chỉ có metric thôi chưa đủ; datasource UID và label phải ổn định thì dashboard-as-code mới thực sự dùng lại được. Khi cố định UID `prometheus`, dashboard JSON trở nên portable hơn giữa các lần chạy mới của Grafana.

---

## 3. Track 03 - Tracing & Logs

Jaeger đã hiển thị trace cho `POST /predict` với các span con:

- `predict`
- `embed-text`
- `vector-search`
- `generate-tokens`

Ảnh `submission/screenshots/jaeger-trace.png` cho thấy flame graph/timeline của request inference. Ảnh `submission/screenshots/jaeger-attrs.png` cho thấy span `generate-tokens` có các attribute theo GenAI semantic conventions, ví dụ:

- `gen_ai.response.finish_reason = stop`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`

Một dòng structured JSON log có `trace_id`:

```json
{"model": "llama3-mock", "input_tokens": 4, "output_tokens": 55, "quality": 0.731, "duration_seconds": 0.3085, "trace_id": "9afb1cc01d3dca605189e483a7f29fc7", "event": "prediction served", "level": "info", "timestamp": "2026-05-11T03:01:19.333017Z"}
```

Tail-sampling math: policy của OTel Collector giữ 100% error traces, 100% traces chậm hơn 2 giây, và 1% healthy traces. Nếu service tạo 10 healthy traces/giây và 1 error trace/giây, số trace được giữ xấp xỉ:

```text
10 * 0.01 + 1 * 1.00 = 1.1 traces/giây
```

Tức là trong incident đó giữ khoảng 10% tổng số trace, còn khi hệ thống khỏe mạnh thì chỉ giữ khoảng 1%. Cách này giúp tiết kiệm storage nhưng vẫn giữ lại những trace có giá trị điều tra cao nhất.

---

## 4. Track 04 - Drift Detection

Kết quả `04-drift-detection/reports/drift-summary.json`:

```json
{
  "prompt_length": {
    "psi": 3.2419,
    "kl": 2.2987,
    "ks_stat": 0.704,
    "ks_pvalue": 0.0,
    "drift": "yes"
  },
  "embedding_norm": {
    "psi": 0.0119,
    "kl": 0.054,
    "ks_stat": 0.046,
    "ks_pvalue": 0.241025,
    "drift": "no"
  },
  "response_length": {
    "psi": 0.0104,
    "kl": 0.0321,
    "ks_stat": 0.036,
    "ks_pvalue": 0.547248,
    "drift": "no"
  },
  "response_quality": {
    "psi": 8.5887,
    "kl": 18.5953,
    "ks_stat": 0.938,
    "ks_pvalue": 0.0,
    "drift": "yes"
  }
}
```

Ảnh report HTML đã được lưu ở `submission/screenshots/drift-report.png`.

Với `prompt_length`, mình chọn PSI làm metric headline vì nó dễ giải thích cho shift dạng phân phối binned giữa baseline và current traffic. Với `embedding_norm`, KS phù hợp cho scalar norm vì nó so sánh hai phân phối liên tục mà không cần chọn bin; nếu theo dõi toàn bộ vector embedding thì MMD sẽ hợp lý hơn vì embedding là dữ liệu đa chiều. Với `response_length`, KS phù hợp để phát hiện thay đổi phân phối liên tục, còn PSI hữu ích hơn khi cần báo cáo cho stakeholder. Với `response_quality`, KS bắt được sự thay đổi rõ trong phân phối quality score, còn KL giúp định lượng mức độ khác biệt giữa hai phân phối khi cả hai có support đủ tốt.

---

## 5. Track 05 - Cross-Day Integration

Dashboard Cross-Day Stack đã render đủ 6 panel cho các ngày 16, 17, 18, 19, 20 và 22. Ảnh evidence được lưu ở:

```text
submission/screenshots/cross-day-dashboard.png
```

Metric khó expose nhất theo mình là Day 20 llama.cpp tokens/sec, vì serving stack thường không có Prometheus endpoint sẵn nếu trước đó chưa instrument server hoặc sidecar. Trong bài lab này mình dùng integration stub để Prometheus scrape được metric đại diện, giúp dashboard cross-day vẫn render khi các lab ngày trước không chạy local. Trong production, stub này nên được thay bằng target thật từ node exporter, Airflow, Spark, Qdrant, llama.cpp và DPO evaluation.

---

## 6. The single change that mattered most

Thay đổi quan trọng nhất là làm cho các định danh trong stack ổn định và có thể join được với nhau: datasource UID `prometheus`, `trace_id` trong structured logs, và service identity thống nhất là `inference-api`. Trước khi có các định danh ổn định này, từng công cụ vẫn chạy riêng lẻ, nhưng người vận hành phải tự nối metric, log và trace bằng mắt. Sau khi chuẩn hóa, dashboard tự resolve datasource, log có thể liên kết tới trace, và Prometheus labels trở nên nhất quán hơn khi điều tra sự cố.

Điều này nối trực tiếp với bài học RED/USE và tracing trong deck: observability không chỉ là thu thập thật nhiều tín hiệu, mà là làm cho các tín hiệu đó có thể liên hệ với nhau thật nhanh khi có incident. Phiên bản hữu ích của stack là phiên bản mình có thể bắt đầu từ burn-rate alert, nhảy sang request metrics, tìm trace liên quan, rồi giải thích vấn đề nằm ở traffic, latency, error, cost hay drift dữ liệu.
