# 💬 ChatBD — Full Featured Chat App

Flask + Socket.IO দিয়ে বানানো রিয়েল-টাইম চ্যাট অ্যাপ।

## ✅ সব Features
- ✅ Register / Login সিস্টেম
- ✅ Profile Picture Upload
- ✅ Online / Offline Status
- ✅ Message Notification (toast popup)
- ✅ Seen Status (✓✓ নীল হয়)
- ✅ Typing... Indicator
- ✅ Emoji Support 😊
- ✅ File & Image Sharing 📎
- ✅ Dark Mode 🌙
- ✅ Group Chat 👥
- ✅ Search User 🔍
- ✅ Real-time messaging (Socket.IO)

## ▶️ চালু করার নিয়ম

### ১. Package install করুন
```
pip install flask flask-socketio
```

### ২. App চালু করুন
```
python app.py
```

### ৩. Browser এ যান
```
http://localhost:5000
```

## 🔑 Test করতে
দুটো Browser tab খুলুন:
- Tab 1: username=`আমি`, password=`1234`
- Tab 2: username=`বন্ধু`, password=`1234`

## 📁 File Structure
```
chatbd/
├── app.py
├── requirements.txt
├── README.md
└── templates/
    ├── login.html
    ├── register.html
    ├── home.html
    ├── chat.html
    └── group_chat.html
```
