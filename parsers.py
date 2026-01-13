"""
PDF Statement Parsers for various financial institutions.
Handles extraction of transactions from bank and credit card statements.
"""
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import pdfplumber


@dataclass
class ExtractedTransaction:
    """Represents a transaction extracted from a PDF statement."""
    date: datetime
    merchant: str
    amount: float
    transaction_type: str  # 'purchase', 'payment', 'refund', 'deposit', 'withdrawal'
    raw_text: str  # Original text from PDF for debugging


@dataclass
class ParseResult:
    """Result of parsing a PDF statement."""
    success: bool
    institution: str
    account_type: str
    account_identifier: Optional[str]  # Last 4 digits or account number
    statement_period: Optional[str]
    transactions: List[ExtractedTransaction]
    error_message: Optional[str] = None


class StatementParser(ABC):
    """Base class for statement parsers."""
    
    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Check if this parser can handle the given PDF text."""
        pass
    
    @abstractmethod
    def parse(self, pdf_path: str) -> ParseResult:
        """Parse the PDF and extract transactions."""
        pass
    
    def _extract_text(self, pdf_path: str) -> str:
        """Extract all text from a PDF file."""
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    
    def _parse_amount(self, amount_str: str) -> float:
        """Parse an amount string to float, handling various formats."""
        # Remove currency symbols and whitespace
        cleaned = re.sub(r'[$,\s]', '', amount_str)
        # Handle parentheses for negative numbers
        if cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = '-' + cleaned[1:-1]
        # Handle CR suffix for credits
        if cleaned.endswith('CR'):
            cleaned = '-' + cleaned[:-2]
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def _parse_date(self, date_str: str, year: int = None) -> Optional[datetime]:
        """Parse a date string to datetime."""
        date_str = date_str.strip()
        formats = [
            '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%m-%d-%y',
            '%m/%d', '%b %d', '%B %d', '%d %b', '%d %B'
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                # If year wasn't in the format, use the provided year
                if '%Y' not in fmt and '%y' not in fmt and year:
                    parsed = parsed.replace(year=year)
                return parsed
            except ValueError:
                continue
        return None


class ChaseParser(StatementParser):
    """Parser for Chase credit card and bank statements."""
    
    def can_parse(self, text: str) -> bool:
        return 'chase' in text.lower() and ('jpmorgan' in text.lower() or 'jpmcb' in text.lower() or 'credit card' in text.lower())
    
    def parse(self, pdf_path: str) -> ParseResult:
        try:
            transactions = []
            account_type = 'credit_card'
            account_identifier = None
            statement_period = None
            
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
                
                # Try to find account number (last 4)
                account_match = re.search(r'Account\s+(?:Number|#)?[:\s]*(?:\*+|x+)?(\d{4})', full_text, re.IGNORECASE)
                if account_match:
                    account_identifier = account_match.group(1)
                
                # Try to find statement period
                period_match = re.search(r'(?:Statement|Billing)\s+(?:Period|Date)[:\s]*(\w+\s+\d{1,2})[,\s]+(\d{4})\s*[-–to]+\s*(\w+\s+\d{1,2})[,\s]+(\d{4})', full_text, re.IGNORECASE)
                if period_match:
                    end_month = period_match.group(3)
                    end_year = period_match.group(4)
                    # Parse to get YYYY-MM format
                    try:
                        end_date = datetime.strptime(f"{end_month} {end_year}", "%B %d %Y")
                        statement_period = end_date.strftime("%Y-%m")
                    except:
                        statement_period = f"{end_year}"
                
                # Determine year from statement
                year_match = re.search(r'20\d{2}', full_text)
                year = int(year_match.group()) if year_match else datetime.now().year
                
                # Parse transactions - Chase format typically: MM/DD Description Amount
                # Look for transaction sections
                transaction_pattern = re.compile(
                    r'(\d{2}/\d{2})\s+'  # Date
                    r'(.+?)\s+'  # Description
                    r'(-?\$?[\d,]+\.\d{2})',  # Amount
                    re.MULTILINE
                )
                
                for match in transaction_pattern.finditer(full_text):
                    date_str = match.group(1)
                    merchant = match.group(2).strip()
                    amount_str = match.group(3)
                    
                    # Skip header rows and totals
                    skip_keywords = ['total', 'balance', 'payment due', 'credit limit', 'available', 'minimum']
                    if any(kw in merchant.lower() for kw in skip_keywords):
                        continue
                    
                    parsed_date = self._parse_date(date_str, year)
                    if not parsed_date:
                        continue
                    
                    amount = self._parse_amount(amount_str)
                    
                    # Determine transaction type
                    trans_type = 'purchase'
                    if amount < 0 or 'payment' in merchant.lower():
                        trans_type = 'payment'
                    elif 'refund' in merchant.lower() or 'credit' in merchant.lower():
                        trans_type = 'refund'
                    
                    transactions.append(ExtractedTransaction(
                        date=parsed_date,
                        merchant=merchant,
                        amount=abs(amount) if trans_type == 'purchase' else -abs(amount),
                        transaction_type=trans_type,
                        raw_text=match.group(0)
                    ))
            
            return ParseResult(
                success=True,
                institution='Chase',
                account_type=account_type,
                account_identifier=account_identifier,
                statement_period=statement_period,
                transactions=transactions
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                institution='Chase',
                account_type='credit_card',
                account_identifier=None,
                statement_period=None,
                transactions=[],
                error_message=str(e)
            )


class AmexParser(StatementParser):
    """Parser for American Express credit card statements."""
    
    def can_parse(self, text: str) -> bool:
        return 'american express' in text.lower() or 'amex' in text.lower()
    
    def parse(self, pdf_path: str) -> ParseResult:
        try:
            transactions = []
            account_identifier = None
            statement_period = None
            
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
                
                # Try to find account number
                account_match = re.search(r'(?:Account|Card)\s*(?:Ending|Number)?[:\s]*(?:\*+|x+)?(\d{4,5})', full_text, re.IGNORECASE)
                if account_match:
                    account_identifier = account_match.group(1)[-4:]  # Last 4 digits
                
                # Try to find statement period
                period_match = re.search(r'(?:Statement|Closing)\s+Date[:\s]*(\w+\s+\d{1,2})[,\s]+(\d{4})', full_text, re.IGNORECASE)
                if period_match:
                    try:
                        end_date = datetime.strptime(f"{period_match.group(1)} {period_match.group(2)}", "%B %d %Y")
                        statement_period = end_date.strftime("%Y-%m")
                    except:
                        pass
                
                # Determine year
                year_match = re.search(r'20\d{2}', full_text)
                year = int(year_match.group()) if year_match else datetime.now().year
                
                # Amex format can vary - typically: MM/DD/YY* Description Reference Amount
                # Try multiple patterns
                patterns = [
                    # Pattern 1: Date Description Amount (simple)
                    re.compile(r'(\d{2}/\d{2}/?\d{0,2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})$', re.MULTILINE),
                    # Pattern 2: Date Description Reference Amount
                    re.compile(r'(\d{2}/\d{2})\s+(.+?)\s+[A-Z0-9]+\s+(-?\$?[\d,]+\.\d{2})', re.MULTILINE),
                ]
                
                for pattern in patterns:
                    for match in pattern.finditer(full_text):
                        date_str = match.group(1)
                        merchant = match.group(2).strip()
                        amount_str = match.group(3)
                        
                        # Skip headers and totals
                        skip_keywords = ['total', 'balance', 'payment', 'credit limit', 'available', 'minimum', 'fee']
                        if any(kw in merchant.lower() for kw in skip_keywords):
                            continue
                        
                        # Skip if merchant is too short (likely parsing error)
                        if len(merchant) < 3:
                            continue
                        
                        parsed_date = self._parse_date(date_str, year)
                        if not parsed_date:
                            continue
                        
                        amount = self._parse_amount(amount_str)
                        
                        # Determine transaction type
                        trans_type = 'purchase'
                        if amount < 0:
                            trans_type = 'payment'
                        elif 'refund' in merchant.lower() or 'credit' in merchant.lower():
                            trans_type = 'refund'
                            amount = -abs(amount)
                        
                        transactions.append(ExtractedTransaction(
                            date=parsed_date,
                            merchant=merchant,
                            amount=abs(amount) if trans_type == 'purchase' else amount,
                            transaction_type=trans_type,
                            raw_text=match.group(0)
                        ))
                    
                    # If we found transactions with this pattern, don't try others
                    if transactions:
                        break
            
            return ParseResult(
                success=True,
                institution='American Express',
                account_type='credit_card',
                account_identifier=account_identifier,
                statement_period=statement_period,
                transactions=transactions
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                institution='American Express',
                account_type='credit_card',
                account_identifier=None,
                statement_period=None,
                transactions=[],
                error_message=str(e)
            )


class TruistParser(StatementParser):
    """Parser for Truist bank statements (checking/savings)."""
    
    def can_parse(self, text: str) -> bool:
        return 'truist' in text.lower() or 'bb&t' in text.lower() or 'suntrust' in text.lower()
    
    def parse(self, pdf_path: str) -> ParseResult:
        try:
            transactions = []
            account_identifier = None
            statement_period = None
            account_type = 'checking'  # Default, could be savings
            
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
                
                # Check if savings account
                if 'savings' in full_text.lower():
                    account_type = 'savings'
                
                # Try to find account number
                account_match = re.search(r'Account\s*(?:Number)?[:\s]*(?:\*+|x+)?(\d{4})', full_text, re.IGNORECASE)
                if account_match:
                    account_identifier = account_match.group(1)
                
                # Try to find statement period
                period_match = re.search(r'(?:Statement\s+Period|From)[:\s]*(\w+\s+\d{1,2})[,\s]+(\d{4})\s*(?:through|to|-)\s*(\w+\s+\d{1,2})[,\s]+(\d{4})', full_text, re.IGNORECASE)
                if period_match:
                    try:
                        end_date = datetime.strptime(f"{period_match.group(3)} {period_match.group(4)}", "%B %d %Y")
                        statement_period = end_date.strftime("%Y-%m")
                    except:
                        pass
                
                # Determine year
                year_match = re.search(r'20\d{2}', full_text)
                year = int(year_match.group()) if year_match else datetime.now().year
                
                # Bank statement format - typically: MM/DD Description Debit Credit Balance
                # or: Date Description Amount
                patterns = [
                    # Pattern for debit/credit columns
                    re.compile(r'(\d{2}/\d{2})\s+(.+?)\s+([\d,]+\.\d{2})?\s*([\d,]+\.\d{2})?\s+[\d,]+\.\d{2}$', re.MULTILINE),
                    # Simple pattern
                    re.compile(r'(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})', re.MULTILINE),
                ]
                
                for pattern in patterns:
                    for match in pattern.finditer(full_text):
                        date_str = match.group(1)
                        merchant = match.group(2).strip()
                        
                        # Handle different column formats
                        if len(match.groups()) >= 4:
                            debit = match.group(3)
                            credit = match.group(4)
                            if debit:
                                amount = self._parse_amount(debit)
                                trans_type = 'withdrawal'
                            elif credit:
                                amount = -self._parse_amount(credit)  # Credits are negative (money in)
                                trans_type = 'deposit'
                            else:
                                continue
                        else:
                            amount = self._parse_amount(match.group(3))
                            trans_type = 'withdrawal' if amount > 0 else 'deposit'
                        
                        # Skip headers and totals
                        skip_keywords = ['balance', 'total', 'beginning', 'ending', 'summary', 'statement']
                        if any(kw in merchant.lower() for kw in skip_keywords):
                            continue
                        
                        if len(merchant) < 3:
                            continue
                        
                        parsed_date = self._parse_date(date_str, year)
                        if not parsed_date:
                            continue
                        
                        # Detect income
                        is_income = trans_type == 'deposit'
                        if 'payroll' in merchant.lower() or 'direct dep' in merchant.lower():
                            is_income = True
                        
                        transactions.append(ExtractedTransaction(
                            date=parsed_date,
                            merchant=merchant,
                            amount=amount,
                            transaction_type=trans_type,
                            raw_text=match.group(0)
                        ))
                    
                    if transactions:
                        break
            
            return ParseResult(
                success=True,
                institution='Truist',
                account_type=account_type,
                account_identifier=account_identifier,
                statement_period=statement_period,
                transactions=transactions
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                institution='Truist',
                account_type='checking',
                account_identifier=None,
                statement_period=None,
                transactions=[],
                error_message=str(e)
            )


class GenericParser(StatementParser):
    """Fallback parser for unrecognized statements."""
    
    def can_parse(self, text: str) -> bool:
        # Always returns True as fallback
        return True
    
    def parse(self, pdf_path: str) -> ParseResult:
        try:
            transactions = []
            
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
                
                # Try to determine institution
                institution = 'Unknown'
                if 'chase' in full_text.lower():
                    institution = 'Chase'
                elif 'american express' in full_text.lower() or 'amex' in full_text.lower():
                    institution = 'American Express'
                elif 'truist' in full_text.lower():
                    institution = 'Truist'
                elif 'bank of america' in full_text.lower():
                    institution = 'Bank of America'
                elif 'wells fargo' in full_text.lower():
                    institution = 'Wells Fargo'
                elif 'citi' in full_text.lower():
                    institution = 'Citi'
                elif 'capital one' in full_text.lower():
                    institution = 'Capital One'
                
                # Determine year
                year_match = re.search(r'20\d{2}', full_text)
                year = int(year_match.group()) if year_match else datetime.now().year
                
                # Generic transaction pattern
                pattern = re.compile(
                    r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+'
                    r'(.+?)\s+'
                    r'(-?\$?[\d,]+\.\d{2})',
                    re.MULTILINE
                )
                
                for match in pattern.finditer(full_text):
                    date_str = match.group(1)
                    merchant = match.group(2).strip()
                    amount_str = match.group(3)
                    
                    # Skip obvious non-transactions
                    skip_keywords = ['total', 'balance', 'summary', 'fee', 'interest', 'minimum']
                    if any(kw in merchant.lower() for kw in skip_keywords):
                        continue
                    
                    if len(merchant) < 3:
                        continue
                    
                    parsed_date = self._parse_date(date_str, year)
                    if not parsed_date:
                        continue
                    
                    amount = self._parse_amount(amount_str)
                    trans_type = 'purchase' if amount > 0 else 'credit'
                    
                    transactions.append(ExtractedTransaction(
                        date=parsed_date,
                        merchant=merchant,
                        amount=amount,
                        transaction_type=trans_type,
                        raw_text=match.group(0)
                    ))
            
            return ParseResult(
                success=True,
                institution=institution,
                account_type='unknown',
                account_identifier=None,
                statement_period=None,
                transactions=transactions
            )
            
        except Exception as e:
            return ParseResult(
                success=False,
                institution='Unknown',
                account_type='unknown',
                account_identifier=None,
                statement_period=None,
                transactions=[],
                error_message=str(e)
            )


class StatementParserFactory:
    """Factory to select appropriate parser for a given statement."""
    
    def __init__(self):
        self.parsers = [
            ChaseParser(),
            AmexParser(),
            TruistParser(),
            GenericParser()  # Fallback, always last
        ]
    
    def get_parser(self, pdf_path: str) -> StatementParser:
        """Determine which parser to use based on PDF content."""
        # Extract text to identify institution
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[:2]:  # Just check first 2 pages
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except:
            pass
        
        for parser in self.parsers:
            if parser.can_parse(text):
                return parser
        
        return self.parsers[-1]  # Return generic parser as fallback
    
    def parse(self, pdf_path: str) -> ParseResult:
        """Parse a PDF statement using the appropriate parser."""
        parser = self.get_parser(pdf_path)
        return parser.parse(pdf_path)
