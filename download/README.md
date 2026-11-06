# Установка одним файлом

Скачайте `vps_setup.sh` кнопкой **Download raw file** на странице файла в GitHub.
Это текстовый самораспаковывающийся комплект, внешнего bootstrap-кода он не скачивает.

```bash
sudo apt-get update
sudo apt-get install -y python3 util-linux
sudo bash vps_setup.sh --install
```

Оба образа latest. Xray inbound и маршруты не создаются. Читайте основной README.
