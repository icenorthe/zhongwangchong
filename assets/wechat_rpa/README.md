把微信 RPA 的模板截图放在这里。

常见命名示例：

- `launch_ad_skip.png`
- `ready_state.png`
- `vehicle_tab.png`
- `go_charge.png`
- `submit_order.png`
- `wechat_pay.png`
- `pay_confirm.png`
- `socket_1.png`
- `socket_2.png`
- `amount_1.png`
- `amount_2.png`

然后在 `config/wechat_rpa_config.json` 里引用，例如：

```json
{
  "launch_ad_skip_image": "launch_ad_skip.png",
  "ready_state_image": "ready_state.png",
  "vehicle_tab_image": "vehicle_tab.png",
  "go_charge_image": "go_charge.png",
  "submit_order_image": "submit_order.png",
  "wechat_pay_image": "wechat_pay.png",
  "pay_confirm_image": "pay_confirm.png",
  "socket_2_image": "socket_2.png",
  "amount_1_image": "amount_1.png"
}
```

