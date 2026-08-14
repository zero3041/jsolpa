# Eventista — by Push

> Công cụ web nội bộ cho luồng đăng ký Eventista và kiểm tra email kích hoạt Outlook.

## Tác giả

**by Push**

## Luồng Eventista

1. Nhập combo Outlook theo định dạng `email|password|refresh_token|client_id` hoặc lấy combo chưa được đánh dấu từ DB.
2. Chọn browser engine, captcha mode, proxy và số job chạy đồng thời trong tab **Reg Eventista**.
3. Mở trang Eventista, mở form đăng ký, điền email/password và gửi form.
4. Chờ trạng thái đăng ký thành công hoặc ghi lại lỗi chi tiết trong **Jobs** và **Log**.
5. Dùng Microsoft Graph để poll hộp thư Outlook, tìm email kích hoạt và trích xuất activation link.
6. Mở activation link, kiểm tra đăng nhập lại, sau đó đánh dấu combo đã hoàn tất Eventista.

## Check mail

Sau khi đăng ký thành công, worker sẽ tự động:

- refresh access token từ `refresh_token` + `client_id`;
- đọc email qua Microsoft Graph;
- lọc subject/body có dấu hiệu activation Eventista;
- trích link `account.faniesta.com/.../verify-email?token=...`;
- retry khi mailbox tạm thời chưa có thư;
- hiển thị thời điểm tìm thấy mail và link trong Job.

Thông tin nhạy cảm chỉ được giữ trong runtime/DB nội bộ. Không commit `.env`, refresh token, mật khẩu, proxy credential hoặc dữ liệu runtime lên GitHub.

## Chạy web UI

```bash
python -m gpt_signup_hybrid web --port 8083
```

Mở `http://127.0.0.1:8083/`, vào tab **Reg Eventista**, rồi nhập combo và bấm **Run Eventista**.

## Kiểm tra nhanh

```bash
.venv/bin/python test/check_eventista.py
```

## Lưu ý

- Chỉ chạy trên tài khoản, mailbox và môi trường mà bạn có quyền kiểm thử.
- Không đưa token, mật khẩu hoặc combo thật vào issue, log công khai hay commit.
- Nếu job lỗi, xem **Log** để phân biệt lỗi browser, captcha, registration, mailbox hay activation.
