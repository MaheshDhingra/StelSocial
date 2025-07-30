from flask import Flask, render_template, redirect, url_for, request, flash, session, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import requests
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
from flask_migrate import Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = User.query.get(user_id)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    profile_picture = db.Column(db.String(200), nullable=True, default='/static/images/default_profile.png') # Default profile picture
    posts = db.relationship('Post', backref='author', lazy=True)
    followed = db.relationship('Follow',
                               foreign_keys='Follow.follower_id',
                               backref='follower', lazy='dynamic',
                               cascade="all, delete-orphan")
    followers = db.relationship('Follow',
                                foreign_keys='Follow.followed_id',
                                backref='followed', lazy='dynamic',
                                cascade="all, delete-orphan")
    
    def follow(self, user):
        if not self.is_following(user):
            f = Follow(follower=self, followed=user)
            db.session.add(f)

    def unfollow(self, user):
        f = self.followed.filter_by(followed_id=user.id).first()
        if f:
            db.session.delete(f)

    def is_following(self, user):
        return self.followed.filter_by(followed_id=user.id).first() is not None

    def get_followed_posts(self):
        followed = Post.query.join(
            Follow, (Follow.followed_id == Post.user_id)
        ).filter(Follow.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.created_at.desc())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(200), nullable=False)
    caption = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")
    likes = db.relationship('Like', backref='post', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Post {self.caption[:20]}>'

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    user = db.relationship('User', backref='comments', lazy=True)

    def __repr__(self):
        return f'<Comment {self.text[:20]}>'

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_uc'),)

    def __repr__(self):
        return f'<Like user_id={self.user_id} post_id={self.post_id}>'

class Follow(db.Model):
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    timestamp = db.Column(db.DateTime, default=db.func.now())

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('user1_id', 'user2_id', name='_user1_user2_uc'),)

    def __repr__(self):
        return f'<Conversation {self.user1_id} and {self.user2_id}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    def __repr__(self):
        return f'<Message {self.text[:20]}>'

# Routes
@app.route('/')
@app.route('/page/<int:page>')
def index(page=1):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    per_page = 10 # Number of posts per page
    posts_pagination = Post.query.order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    posts = posts_pagination.items
    return render_template('index.html', posts=posts, current_user=g.user, pagination=posts_pagination)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists. Please choose a different one.', 'danger')
        else:
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    if 'user_id' not in session:
        flash('Please log in to create a post.', 'warning')
        return redirect(url_for('login'))
    if request.method == 'POST':
        image_url = request.form['image_url']
        caption = request.form['caption']
        user_id = session['user_id']
        new_post = Post(image_url=image_url, caption=caption, user_id=user_id)
        db.session.add(new_post)
        db.session.commit()
        flash('Post created successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('create_post.html')

@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).all()
    return render_template('profile.html', user=user, posts=posts, current_user=g.user)

@app.route('/follow/<username>', methods=['POST'])
def follow_user(username):
    if 'user_id' not in session:
        flash('Please log in to follow users.', 'warning')
        return redirect(url_for('login'))
    
    user_to_follow = User.query.filter_by(username=username).first_or_404()
    if user_to_follow.id == session['user_id']:
        flash('You cannot follow yourself!', 'danger')
        return redirect(url_for('profile', username=username))
    
    g.user.follow(user_to_follow)
    db.session.commit()
    flash(f'You are now following {username}!', 'success')
    return redirect(url_for('profile', username=username))

@app.route('/unfollow/<username>', methods=['POST'])
def unfollow_user(username):
    if 'user_id' not in session:
        flash('Please log in to unfollow users.', 'warning')
        return redirect(url_for('login'))
    
    user_to_unfollow = User.query.filter_by(username=username).first_or_404()
    if user_to_unfollow.id == session['user_id']:
        flash('You cannot unfollow yourself!', 'danger')
        return redirect(url_for('profile', username=username))
    
    g.user.unfollow(user_to_unfollow)
    db.session.commit()
    flash(f'You have unfollowed {username}.', 'info')
    return redirect(url_for('profile', username=username))

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash('Please log in to edit your profile.', 'warning')
        return redirect(url_for('login'))
    
    user = g.user
    if request.method == 'POST':
        user.bio = request.form['bio']
        # Handle profile picture upload (simplified for now, just URL)
        new_profile_picture = request.form['profile_picture']
        if new_profile_picture:
            user.profile_picture = new_profile_picture
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile', username=user.username))
    
    return render_template('edit_profile.html', user=user)

@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user_id' not in session:
        flash('Please log in to edit posts.', 'warning')
        return redirect(url_for('login'))
    post = Post.query.get_or_404(post_id)
    if post.user_id != session['user_id']:
        flash('You are not authorized to edit this post.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        post.image_url = request.form['image_url']
        post.caption = request.form['caption']
        db.session.commit()
        flash('Post updated successfully!', 'success')
        return redirect(url_for('profile', username=session['username']))
    return render_template('edit_post.html', post=post)

@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        flash('Please log in to delete posts.', 'warning')
        return redirect(url_for('login'))
    post = Post.query.get_or_404(post_id)
    if post.user_id != session['user_id']:
        flash('You are not authorized to delete this post.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(post)
    db.session.commit()
    flash('Post deleted successfully!', 'success')
    return redirect(url_for('profile', username=session['username']))

@app.route('/add_comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        flash('Please log in to comment.', 'warning')
        return redirect(url_for('login'))
    
    post = Post.query.get_or_404(post_id)
    comment_text = request.form['comment_text']
    if not comment_text:
        flash('Comment cannot be empty.', 'danger')
        return redirect(url_for('index'))

    new_comment = Comment(text=comment_text, user_id=session['user_id'], post_id=post.id)
    db.session.add(new_comment)
    db.session.commit()
    flash('Comment added successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/like_post/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        flash('Please log in to like posts.', 'warning')
        return redirect(url_for('login'))

    post = Post.query.get_or_404(post_id)
    user_id = session['user_id']
    
    existing_like = Like.query.filter_by(user_id=user_id, post_id=post.id).first()
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        flash('Post unliked.', 'info')
    else:
        new_like = Like(user_id=user_id, post_id=post.id)
        db.session.add(new_like)
        db.session.commit()
        flash('Post liked!', 'success')
    
    return redirect(url_for('index'))

# External API Integration (Cat Fact API)
@app.route('/cat_fact')
def cat_fact():
    if 'user_id' not in session:
        flash('Please log in to view cat facts.', 'warning')
        return redirect(url_for('login'))

    url = "https://catfact.ninja/fact"
    try:
        response = requests.get(url)
        response.raise_for_status() # Raise an exception for HTTP errors
        cat_fact_data = response.json()
        return render_template('cat_fact.html', cat_fact=cat_fact_data.get('fact'))
    except requests.exceptions.RequestException as e:
        flash(f"Error fetching cat fact: {e}", 'danger')
        return render_template('cat_fact.html', cat_fact=None)

@app.route('/search')
def search():
    query = request.args.get('query', '')
    if not query:
        flash('Please enter a search query.', 'info')
        return render_template('index.html', posts=[], current_user=g.user) # Or a dedicated search results page

    # Search for users by username
    users = User.query.filter(User.username.ilike(f'%{query}%')).all()
    
    # Search for posts by caption
    posts = Post.query.filter(Post.caption.ilike(f'%{query}%')).order_by(Post.created_at.desc()).all()

    return render_template('search_results.html', query=query, users=users, posts=posts, current_user=g.user)

@app.route('/messages')
def messages():
    if 'user_id' not in session:
        flash('Please log in to view messages.', 'warning')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conversations = Conversation.query.filter(
        (Conversation.user1_id == user_id) | (Conversation.user2_id == user_id)
    ).all()

    # Get the other participant's username for each conversation
    for conv in conversations:
        if conv.user1_id == user_id:
            other_user_id = conv.user2_id
        else:
            other_user_id = conv.user1_id
        conv.other_user = User.query.get(other_user_id)

    return render_template('messages.html', conversations=conversations)

@app.route('/conversation/<int:other_user_id>', methods=['GET', 'POST'])
def conversation(other_user_id):
    if 'user_id' not in session:
        flash('Please log in to view messages.', 'warning')
        return redirect(url_for('login'))

    current_user_id = session['user_id']
    other_user = User.query.get_or_404(other_user_id)

    # Find or create conversation
    conv = Conversation.query.filter(
        ((Conversation.user1_id == current_user_id) & (Conversation.user2_id == other_user_id)) |
        ((Conversation.user1_id == other_user_id) & (Conversation.user2_id == current_user_id))
    ).first()

    if not conv:
        conv = Conversation(user1_id=current_user_id, user2_id=other_user_id)
        db.session.add(conv)
        db.session.commit()

    if request.method == 'POST':
        message_text = request.form['message_text']
        if not message_text:
            flash('Message cannot be empty.', 'danger')
        else:
            new_message = Message(conversation_id=conv.id, sender_id=current_user_id, text=message_text)
            db.session.add(new_message)
            db.session.commit()
            return redirect(url_for('conversation', other_user_id=other_user_id))

    messages = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
    
    # Attach sender username to each message
    for message in messages:
        message.sender_username = User.query.get(message.sender_id).username

    return render_template('conversation.html', conversation=conv, other_user=other_user, messages=messages, current_user_id=current_user_id)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
