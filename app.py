"""
Budget & Spending Analysis API
Flask application providing endpoints for PDF upload, parsing, and transaction management.
"""
import os
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from models import db, Account, Category, Transaction, MerchantMapping, StatementUpload
from parsers import StatementParserFactory

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'pdf'}
STATIC_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///budget.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload

CORS(app)
db.init_app(app)

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_categories():
    """Initialize default categories if they don't exist."""
    default_categories = [
        ('Food & Dining', None, False, [
            ('Groceries', False),
            ('Restaurants', False),
            ('Coffee Shops', False),
            ('Fast Food', False),
            ('Bars & Alcohol', False),
        ]),
        ('Transportation', None, False, [
            ('Gas', False),
            ('Public Transit', False),
            ('Rideshare', False),
            ('Parking', False),
            ('Auto Maintenance', False),
        ]),
        ('Housing', None, False, [
            ('Rent/Mortgage', False),
            ('Utilities', False),
            ('Home Maintenance', False),
            ('Home Insurance', False),
        ]),
        ('Entertainment', None, False, [
            ('Streaming Services', False),
            ('Events/Concerts', False),
            ('Movies', False),
            ('Games', False),
            ('Hobbies', False),
        ]),
        ('Shopping', None, False, [
            ('Clothing', False),
            ('Electronics', False),
            ('Home Goods', False),
            ('Online Shopping', False),
        ]),
        ('Health & Fitness', None, False, [
            ('Gym', False),
            ('Medical', False),
            ('Pharmacy', False),
            ('Personal Care', False),
        ]),
        ('Travel', None, False, [
            ('Flights', False),
            ('Hotels', False),
            ('Car Rental', False),
            ('Vacation', False),
        ]),
        ('Bills & Utilities', None, False, [
            ('Phone', False),
            ('Internet', False),
            ('Insurance', False),
            ('Subscriptions', False),
        ]),
        ('Financial', None, False, [
            ('Bank Fees', False),
            ('Interest', False),
            ('Investments', False),
            ('Taxes', False),
        ]),
        ('Income', None, True, [
            ('Salary', True),
            ('Freelance', True),
            ('Investments', True),
            ('Refunds', True),
            ('Other Income', True),
        ]),
        ('Other', None, False, [
            ('Miscellaneous', False),
            ('Uncategorized', False),
        ]),
    ]
    
    for broad_name, _, is_income, subcats in default_categories:
        # Check if parent category exists
        parent = Category.query.filter_by(name=broad_name, parent_id=None).first()
        if not parent:
            parent = Category(name=broad_name, is_income=is_income)
            db.session.add(parent)
            db.session.flush()  # Get the ID
            
            # Add subcategories
            for sub_name, sub_income in subcats:
                sub = Category(name=sub_name, parent_id=parent.id, is_income=sub_income)
                db.session.add(sub)
    
    db.session.commit()


# Create tables on first request
@app.before_request
def create_tables():
    if not hasattr(app, '_tables_created'):
        db.create_all()
        init_categories()
        app._tables_created = True


# ============== API Endpoints ==============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})


# ---------- Upload Endpoints ----------

@app.route('/api/upload', methods=['POST'])
def upload_statement():
    """Upload a PDF statement for processing."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files are allowed'}), 400
    
    # Save file
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_filename = f"{timestamp}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)
    
    # Create upload record
    upload = StatementUpload(
        filename=filename,
        status='pending'
    )
    db.session.add(upload)
    db.session.commit()
    
    # Process the PDF
    try:
        parser_factory = StatementParserFactory()
        result = parser_factory.parse(filepath)
        
        if not result.success:
            upload.status = 'error'
            upload.error_message = result.error_message
            db.session.commit()
            return jsonify({
                'error': 'Failed to parse statement',
                'details': result.error_message,
                'upload_id': upload.id
            }), 400
        
        # Get or create account
        account = Account.query.filter_by(
            institution=result.institution,
            last_four=result.account_identifier
        ).first()
        
        if not account:
            account = Account(
                name=f"{result.institution} {result.account_type.replace('_', ' ').title()}",
                account_type=result.account_type,
                institution=result.institution,
                last_four=result.account_identifier
            )
            db.session.add(account)
            db.session.flush()
        
        # Store transactions
        transaction_count = 0
        for txn in result.transactions:
            # Check for duplicates
            existing = Transaction.query.filter_by(
                date=txn.date.date(),
                raw_merchant=txn.merchant,
                amount=txn.amount,
                account_id=account.id
            ).first()
            
            if not existing:
                new_txn = Transaction(
                    date=txn.date.date(),
                    raw_merchant=txn.merchant,
                    amount=txn.amount,
                    transaction_type=txn.transaction_type,
                    account_id=account.id,
                    statement_file=unique_filename,
                    statement_period=result.statement_period,
                    is_income=txn.transaction_type in ('deposit', 'credit') and txn.amount < 0,
                    needs_review=True
                )
                db.session.add(new_txn)
                transaction_count += 1
        
        # Update upload record
        upload.institution = result.institution
        upload.account_id = account.id
        upload.statement_period = result.statement_period
        upload.transaction_count = transaction_count
        upload.status = 'processed'
        upload.processed_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'upload_id': upload.id,
            'institution': result.institution,
            'account': account.to_dict(),
            'statement_period': result.statement_period,
            'transactions_imported': transaction_count,
            'total_in_statement': len(result.transactions),
            'duplicates_skipped': len(result.transactions) - transaction_count
        })
        
    except Exception as e:
        upload.status = 'error'
        upload.error_message = str(e)
        db.session.commit()
        return jsonify({'error': str(e), 'upload_id': upload.id}), 500


@app.route('/api/uploads', methods=['GET'])
def get_uploads():
    """Get list of all uploaded statements."""
    uploads = StatementUpload.query.order_by(StatementUpload.uploaded_at.desc()).all()
    return jsonify([u.to_dict() for u in uploads])


@app.route('/api/uploads/<int:upload_id>', methods=['GET'])
def get_upload(upload_id):
    """Get details of a specific upload."""
    upload = StatementUpload.query.get_or_404(upload_id)
    return jsonify(upload.to_dict())


# ---------- Transaction Endpoints ----------

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """Get transactions with optional filtering."""
    # Query params
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    account_id = request.args.get('account_id', type=int)
    category_id = request.args.get('category_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    needs_review = request.args.get('needs_review', type=lambda x: x.lower() == 'true')
    
    query = Transaction.query
    
    if account_id:
        query = query.filter_by(account_id=account_id)
    if category_id:
        query = query.filter_by(category_id=category_id)
    if needs_review is not None:
        query = query.filter_by(needs_review=needs_review)
    if start_date:
        query = query.filter(Transaction.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(Transaction.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
    
    # Order by date descending
    query = query.order_by(Transaction.date.desc())
    
    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'transactions': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'per_page': per_page
    })


@app.route('/api/transactions/<int:txn_id>', methods=['GET'])
def get_transaction(txn_id):
    """Get a specific transaction."""
    txn = Transaction.query.get_or_404(txn_id)
    return jsonify(txn.to_dict())


@app.route('/api/transactions/<int:txn_id>', methods=['PATCH'])
def update_transaction(txn_id):
    """Update a transaction (categorization, etc.)."""
    txn = Transaction.query.get_or_404(txn_id)
    data = request.get_json()
    
    if 'category_id' in data:
        txn.category_id = data['category_id']
    if 'normalized_merchant' in data:
        txn.normalized_merchant = data['normalized_merchant']
    if 'is_income' in data:
        txn.is_income = data['is_income']
    if 'is_subscription' in data:
        txn.is_subscription = data['is_subscription']
    if 'needs_review' in data:
        txn.needs_review = data['needs_review']
    
    db.session.commit()
    return jsonify(txn.to_dict())


# ---------- Account Endpoints ----------

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """Get all accounts."""
    accounts = Account.query.all()
    return jsonify([a.to_dict() for a in accounts])


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
def get_account(account_id):
    """Get a specific account."""
    account = Account.query.get_or_404(account_id)
    return jsonify(account.to_dict())


# ---------- Category Endpoints ----------

@app.route('/api/categories', methods=['GET'])
def get_categories():
    """Get all categories (hierarchical)."""
    # Get top-level categories
    parents = Category.query.filter_by(parent_id=None).all()
    return jsonify([c.to_dict(include_subcategories=True) for c in parents])


@app.route('/api/categories/flat', methods=['GET'])
def get_categories_flat():
    """Get all categories as flat list."""
    categories = Category.query.all()
    return jsonify([c.to_dict() for c in categories])


# ---------- Summary/Stats Endpoints ----------

@app.route('/api/summary', methods=['GET'])
def get_summary():
    """Get overall spending summary."""
    # Optional date filters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Transaction.query.filter_by(is_income=False)
    
    if start_date:
        query = query.filter(Transaction.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(Transaction.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
    
    transactions = query.all()
    
    total_spending = sum(t.amount for t in transactions if t.amount > 0)
    total_income = abs(sum(t.amount for t in Transaction.query.filter_by(is_income=True).all()))
    transaction_count = len(transactions)
    
    # By account
    by_account = {}
    for t in transactions:
        acc_name = t.account.name if t.account else 'Unknown'
        by_account[acc_name] = by_account.get(acc_name, 0) + t.amount
    
    return jsonify({
        'total_spending': round(total_spending, 2),
        'total_income': round(total_income, 2),
        'transaction_count': transaction_count,
        'by_account': by_account,
        'needs_review_count': Transaction.query.filter_by(needs_review=True).count()
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


# Serve React frontend in production
@app.route('/')
@app.route('/<path:path>')
def serve_frontend(path=''):
    if path and os.path.exists(os.path.join(STATIC_FOLDER, path)):
        return send_from_directory(STATIC_FOLDER, path)
    return send_from_directory(STATIC_FOLDER, 'index.html')
