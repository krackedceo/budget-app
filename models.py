"""
Database models for the Budget & Spending Analysis application.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    """Represents a bank or credit card account."""
    __tablename__ = 'accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)  # 'credit_card', 'checking', 'savings'
    institution = db.Column(db.String(100), nullable=False)  # 'Chase', 'Amex', 'Truist'
    last_four = db.Column(db.String(4), nullable=True)  # Last 4 digits if available
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    transactions = db.relationship('Transaction', backref='account', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'account_type': self.account_type,
            'institution': self.institution,
            'last_four': self.last_four,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Category(db.Model):
    """Represents spending categories with two-level hierarchy."""
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    is_income = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    parent = db.relationship('Category', remote_side=[id], backref='subcategories')
    
    def to_dict(self, include_subcategories=False):
        result = {
            'id': self.id,
            'name': self.name,
            'parent_id': self.parent_id,
            'is_income': self.is_income
        }
        if include_subcategories and not self.parent_id:
            result['subcategories'] = [sub.to_dict() for sub in self.subcategories]
        return result


class MerchantMapping(db.Model):
    """Maps raw merchant names to normalized names and categories."""
    __tablename__ = 'merchant_mappings'
    
    id = db.Column(db.Integer, primary_key=True)
    raw_name = db.Column(db.String(255), nullable=False, unique=True)
    normalized_name = db.Column(db.String(255), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    is_approved = db.Column(db.Boolean, default=False)  # User has approved this mapping
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    category = db.relationship('Category')
    
    def to_dict(self):
        return {
            'id': self.id,
            'raw_name': self.raw_name,
            'normalized_name': self.normalized_name,
            'category_id': self.category_id,
            'category': self.category.to_dict() if self.category else None,
            'is_approved': self.is_approved
        }


class Transaction(db.Model):
    """Individual financial transaction extracted from statements."""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    raw_merchant = db.Column(db.String(255), nullable=False)
    normalized_merchant = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Float, nullable=False)  # Positive = expense, Negative = credit/income
    transaction_type = db.Column(db.String(50), nullable=True)  # 'purchase', 'payment', 'refund', etc.
    
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    
    # Flags
    is_income = db.Column(db.Boolean, default=False)
    is_subscription = db.Column(db.Boolean, default=False)
    needs_review = db.Column(db.Boolean, default=True)
    
    # Source tracking
    statement_file = db.Column(db.String(255), nullable=True)
    statement_period = db.Column(db.String(50), nullable=True)  # e.g., "2024-01"
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    category = db.relationship('Category')
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'raw_merchant': self.raw_merchant,
            'normalized_merchant': self.normalized_merchant,
            'amount': self.amount,
            'transaction_type': self.transaction_type,
            'account_id': self.account_id,
            'account': self.account.to_dict() if self.account else None,
            'category_id': self.category_id,
            'category': self.category.to_dict() if self.category else None,
            'is_income': self.is_income,
            'is_subscription': self.is_subscription,
            'needs_review': self.needs_review,
            'statement_file': self.statement_file,
            'statement_period': self.statement_period
        }


class StatementUpload(db.Model):
    """Tracks uploaded statement files."""
    __tablename__ = 'statement_uploads'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    institution = db.Column(db.String(100), nullable=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    statement_period = db.Column(db.String(50), nullable=True)
    transaction_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='pending')  # 'pending', 'processed', 'error'
    error_message = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    
    account = db.relationship('Account')
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'institution': self.institution,
            'account_id': self.account_id,
            'account': self.account.to_dict() if self.account else None,
            'statement_period': self.statement_period,
            'transaction_count': self.transaction_count,
            'status': self.status,
            'error_message': self.error_message,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None
        }
