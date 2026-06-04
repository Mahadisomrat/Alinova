from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import os, json

app = Flask(__name__)
app.secret_key = 'chatbd_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

users = {}
messages = {}
group_messages = {}
groups = {}
online_users = set()
user_rooms = {}


def get_room_id(u1, u2):
    return '_'.join(sorted([u1, u2]))


@app.route('/')
def index():
    return redirect(url_for('login') if 'username' not in session else url_for('home'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        if not u or not p:
            error = 'সব তথ্য পূরণ করুন।'
        elif u in users:
            error = 'এই নামে ইউজার আছে।'
        else:
            users[u] = {'password': p, 'profile_pic': None, 'about': 'Hey! I am using ChatBD'}
            session['username'] = u
            return redirect(url_for('home'))
    return render_template('register.html', error=error)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        if users.get(u, {}).get('password') == p:
            session['username'] = u
            return redirect(url_for('home'))
        error = 'ভুল নাম বা পাসওয়ার্ড।'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


@app.route('/home')
def home():
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    others = [u for u in users if u != me]
    my_groups = [g for g, d in groups.items() if me in d['members']]
    return render_template('home.html', username=me, users=others,
                           online=list(online_users), users_data=users,
                           groups=my_groups, groups_data=groups)


@app.route('/chat/<other>')
def chat(other):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    if other not in users: return redirect(url_for('home'))
    room = get_room_id(me, other)
    history = messages.get(room, [])
    return render_template('chat.html', me=me, other=other,
                           history=history, room=room, users_data=users,
                           online=list(online_users))


@app.route('/group/<name>')
def group_chat(name):
    if 'username' not in session: return redirect(url_for('login'))
    me = session['username']
    if name not in groups or me not in groups[name]['members']:
        return redirect(url_for('home'))
    history = group_messages.get(name, [])
    return render_template('group_chat.html', me=me, group_name=name,
                           history=history, group=groups[name], users_data=users)


@app.route('/upload_pic', methods=['POST'])
def upload_pic():
    if 'username' not in session: return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    pic = data.get('pic')
    if pic:
        users[session['username']]['profile_pic'] = pic
        socketio.emit('profile_updated', {'username': session['username'], 'profile_pic': pic})
        return jsonify({'success': True})
    return jsonify({'error': 'no image'}), 400


@app.route('/create_group', methods=['POST'])
def create_group():
    if 'username' not in session: return jsonify({'error': 'not logged in'}), 401
    data = request.get_json()
    name = data.get('name', '').strip()
    members = data.get('members', [])
    me = session['username']
    if not name: return jsonify({'error': 'নাম দিন'}), 400
    if name in groups: return jsonify({'error': 'এই নামে গ্রুপ আছে'}), 400
    if me not in members: members.append(me)
    groups[name] = {'members': members, 'created_by': me, 'pic': None}
    group_messages[name] = []
    socketio.emit('group_created', {'name': name, 'members': members})
    return jsonify({'success': True, 'name': name})


# ─── Socket Events ────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    if 'username' in session:
        u = session['username']
        online_users.add(u)
        user_rooms[u] = request.sid
        emit('user_status', {'user': u, 'status': 'online'}, broadcast=True)


@socketio.on('disconnect')
def on_disconnect():
    if 'username' in session:
        u = session['username']
        online_users.discard(u)
        user_rooms.pop(u, None)
        emit('user_status', {'user': u, 'status': 'offline'}, broadcast=True)


@socketio.on('join')
def on_join(data):
    join_room(data['room'])


@socketio.on('typing')
def on_typing(data):
    emit('typing', {'user': data['user'], 'room': data['room']}, room=data['room'], include_self=False)


@socketio.on('stop_typing')
def on_stop_typing(data):
    emit('stop_typing', {'user': data['user'], 'room': data['room']}, room=data['room'], include_self=False)


@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    sender = data['from']
    msg = {
        'from': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'reply_to': data.get('reply_to'),
        'time': datetime.now().strftime('%I:%M %p'),
        'seen': False,
        'edited': False,
        'deleted': False,
        'reactions': {},
        'profile_pic': users.get(sender, {}).get('profile_pic'),
        'id': datetime.now().strftime('%f')
    }
    if room not in messages: messages[room] = []
    messages[room].append(msg)
    emit('receive_message', msg, room=room)
    emit('new_notification', {
        'from': sender,
        'text': data.get('text', '📎 File'),
        'room': room,
        'profile_pic': users.get(sender, {}).get('profile_pic')
    }, broadcast=True)


@socketio.on('send_group_message')
def handle_group_message(data):
    gname = data['group']
    sender = data['from']
    msg = {
        'from': sender,
        'text': data.get('text', ''),
        'file': data.get('file'),
        'file_name': data.get('file_name'),
        'file_type': data.get('file_type'),
        'duration': data.get('duration'),
        'time': datetime.now().strftime('%I:%M %p'),
        'profile_pic': users.get(sender, {}).get('profile_pic'),
        'id': datetime.now().strftime('%f')
    }
    if gname not in group_messages: group_messages[gname] = []
    group_messages[gname].append(msg)
    emit('receive_group_message', msg, room='group_' + gname)


@socketio.on('join_group')
def on_join_group(data):
    join_room('group_' + data['group'])


@socketio.on('message_seen')
def on_seen(data):
    emit('message_seen', {'room': data['room']}, room=data['room'], include_self=False)


@socketio.on('delete_message')
def on_delete(data):
    room = data['room']
    msg_id = int(data['msg_id'])
    if room in messages and msg_id < len(messages[room]):
        messages[room][msg_id]['text'] = ''
        messages[room][msg_id]['deleted'] = True
    emit('message_deleted', {'room': room, 'msg_id': msg_id}, room=room)


@socketio.on('edit_message')
def on_edit(data):
    room = data['room']
    msg_id = int(data['msg_id'])
    new_text = data['new_text']
    if room in messages and msg_id < len(messages[room]):
        messages[room][msg_id]['text'] = new_text
        messages[room][msg_id]['edited'] = True
    emit('message_edited', {'room': room, 'msg_id': msg_id, 'new_text': new_text}, room=room)


@socketio.on('react_message')
def on_react(data):
    room = data['room']
    msg_id = int(data['msg_id'])
    emoji = data['emoji']
    if room in messages and msg_id < len(messages[room]):
        msg = messages[room][msg_id]
        if 'reactions' not in msg:
            msg['reactions'] = {}
        msg['reactions'][emoji] = msg['reactions'].get(emoji, 0) + 1
        emit('message_reaction', {'room': room, 'msg_id': msg_id, 'reactions': msg['reactions']}, room=room)


if __name__ == '__main__':
    users['আমি'] = {'password': '1234', 'profile_pic': None, 'about': 'Hey! I am using ChatBD'}
    users['বন্ধু'] = {'password': '1234', 'profile_pic': None, 'about': 'Available'}
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)