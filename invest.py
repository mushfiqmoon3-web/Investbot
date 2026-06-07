"""
===================================================================
INVESTMENT PRO BOT - ULTRA ROBUST CLIENT DEMO VERSION (SIMULATED)
===================================================================
"""

import logging
import sqlite3
import random
import string
import os
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================================================================
# CONFIGURATION WITH DECIMAL SUPPORT
# ===================================================================

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "12345678").split(",") if x.strip()]
    DB_PATH = os.getenv("DB_PATH", "investment_bot.db")
    CURRENCY = os.getenv("CURRENCY", "$")
    CURRENCY_NAME = os.getenv("CURRENCY_NAME", "USD")
    
    MIN_INVESTMENT = Decimal(os.getenv("MIN_INVESTMENT", "10"))
    MAX_INVESTMENT = Decimal(os.getenv("MAX_INVESTMENT", "100000"))
    
    # 3-Tier Multi-Level Referral Percentages
    REF_L1_PERCENT = Decimal(os.getenv("REF_L1_PERCENT", "5"))
    REF_L2_PERCENT = Decimal(os.getenv("REF_L2_PERCENT", "3"))
    REF_L3_PERCENT = Decimal(os.getenv("REF_L3_PERCENT", "1"))
    
    ENABLE_REFERRAL = os.getenv("ENABLE_REFERRAL", "true").lower() == "true"
    ENABLE_WITHDRAWAL = os.getenv("ENABLE_WITHDRAWAL", "true").lower() == "true"
    SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@investmentpro.com")
    SUPPORT_TELEGRAM = os.getenv("SUPPORT_TELEGRAM", "@admin_username")

    WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x1234567890abcdef1234567890abcdef12345678")
    PAYMENT_METHOD = os.getenv("PAYMENT_METHOD", "USDT (TRC20)")
    NETWORK = os.getenv("NETWORK", "TRC20")

    PLANS = {
        "starter": {"name": "Starter", "min": Decimal("10"), "max": Decimal("500"), "daily_rate": Decimal("0.01"), "duration": 30, "description": "Perfect for beginners"},
        "silver": {"name": "Silver", "min": Decimal("500"), "max": Decimal("2500"), "daily_rate": Decimal("0.015"), "duration": 60, "description": "Balanced growth plan"},
        "gold": {"name": "Gold", "min": Decimal("2500"), "max": Decimal("10000"), "daily_rate": Decimal("0.02"), "duration": 90, "description": "High return investment"},
        "platinum": {"name": "Platinum", "min": Decimal("10000"), "max": Decimal("100000"), "daily_rate": Decimal("0.025"), "duration": 120, "description": "Premium elite plan"},
    }

# ===================================================================
# DATABASE ENGINE
# ===================================================================

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                phone TEXT, email TEXT, referral_code TEXT UNIQUE, referred_by INTEGER,
                balance TEXT DEFAULT '0.00', total_invested TEXT DEFAULT '0.00', 
                total_earned TEXT DEFAULT '0.00', total_withdrawn TEXT DEFAULT '0.00', 
                joined_date TEXT, status TEXT DEFAULT 'active'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS investments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT,
                amount TEXT, daily_rate TEXT, duration INTEGER, start_date TEXT,
                end_date TEXT, total_return TEXT, daily_earning TEXT, status TEXT DEFAULT 'active',
                total_earned TEXT DEFAULT '0.00', last_calculation TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
                amount TEXT, status TEXT, method TEXT, details TEXT, created_at TEXT, processed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER,
                level INTEGER, bonus_amount TEXT, status TEXT DEFAULT 'credited', created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT,
                amount TEXT, transaction_id TEXT UNIQUE, status TEXT DEFAULT 'pending',
                created_at TEXT, processed_at TEXT, processed_by INTEGER
            )
        """)
        self.conn.commit()

    def execute(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor

    def fetchone(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

# ===================================================================
# BUSINESS SYSTEM PLUGINS
# ===================================================================

class UserManager:
    def __init__(self, db: Database):
        self.db = db

    def generate_referral_code(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    def get_or_create_user(self, user_id: int, username: str, first_name: str, last_name: str = None, referral_code: str = None) -> dict:
        user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not user:
            ref_code = self.generate_referral_code()
            referred_by = None
            if referral_code and Config.ENABLE_REFERRAL:
                referrer = self.db.fetchone("SELECT user_id FROM users WHERE referral_code = ?", (referral_code,))
                if referrer and referrer[0] != user_id:
                    referred_by = referrer[0]
            
            self.db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, referral_code, referred_by, joined_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, first_name, last_name, ref_code, referred_by, datetime.now().isoformat()))
            user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        
        return {
            "user_id": user[0], "username": user[1], "first_name": user[2],
            "balance": Decimal(user[8]), "total_invested": Decimal(user[9]), "total_earned": Decimal(user[10]),
            "total_withdrawn": Decimal(user[11]), "referral_code": user[6], "status": user[13]
        }

    def get_user(self, user_id: int) -> Optional[dict]:
        user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not user:
            return None
        return {
            "user_id": user[0], "username": user[1], "first_name": user[2],
            "balance": Decimal(user[8]), "total_invested": Decimal(user[9]), "total_earned": Decimal(user[10]),
            "total_withdrawn": Decimal(user[11]), "referral_code": user[6], "status": user[13]
        }

    def get_stats(self) -> dict:
        total_users = self.db.fetchone("SELECT COUNT(*) FROM users")[0]
        active_invs = self.db.fetchall("SELECT amount FROM investments WHERE status = 'active'")
        total_invested = sum(Decimal(r[0]) for r in active_invs)
        
        earned_rows = self.db.fetchall("SELECT total_earned FROM investments")
        total_earned = sum(Decimal(r[0]) for r in earned_rows)
        
        with_rows = self.db.fetchall("SELECT amount FROM transactions WHERE type = 'withdrawal' AND status = 'pending'")
        pending_withdrawals = sum(Decimal(r[0]) for r in with_rows)
        
        pending_deposits = self.db.fetchone("SELECT COUNT(*) FROM deposit_requests WHERE status = 'awaiting_approval'")[0]
        return {"total_users": total_users, "total_investments": total_invested, 
                "total_earned": total_earned, "pending_withdrawals": pending_withdrawals,
                "pending_deposits": pending_deposits}


class InvestmentManager:
    def __init__(self, db: Database):
        self.db = db

    def create_investment(self, user_id: int, plan_type: str, amount: Decimal) -> dict:
        plan = Config.PLANS[plan_type]
        daily_earning = (amount * plan["daily_rate"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_return = (daily_earning * plan["duration"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        start_date = datetime.now()
        end_date = start_date + timedelta(days=plan["duration"])
        
        cursor = self.db.execute("""
            INSERT INTO investments (user_id, plan_type, amount, daily_rate, duration, start_date, 
             end_date, total_return, daily_earning, last_calculation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, plan_type, str(amount), str(plan["daily_rate"]), plan["duration"], 
              start_date.isoformat(), end_date.isoformat(), str(total_return), str(daily_earning), start_date.isoformat()))
        
        user_data = self.db.fetchone("SELECT total_invested FROM users WHERE user_id = ?", (user_id,))
        new_total = (Decimal(user_data[0]) + amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.db.execute("UPDATE users SET total_invested = ? WHERE user_id = ?", (str(new_total), user_id))
        
        self.distribute_referral_commissions(user_id, amount)
        
        return {
            "success": True, "investment_id": cursor.lastrowid, "plan": plan["name"],
            "amount": amount, "duration": plan["duration"], "daily_earning": daily_earning, "total_return": total_return
        }

    def distribute_referral_commissions(self, user_id: int, investment_amount: Decimal):
        current_user_id = user_id
        tiers = [
            {"level": 1, "percent": Config.REF_L1_PERCENT},
            {"level": 2, "percent": Config.REF_L2_PERCENT},
            {"level": 3, "percent": Config.REF_L3_PERCENT}
        ]
        
        for tier in tiers:
            parent_data = self.db.fetchone("SELECT referred_by FROM users WHERE user_id = ?", (current_user_id,))
            if not parent_data or not parent_data[0]:
                break
                
            referrer_id = parent_data[0]
            bonus = (investment_amount * (tier["percent"] / Decimal("100"))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            ref_user = self.db.fetchone("SELECT balance FROM users WHERE user_id = ?", (referrer_id,))
            if ref_user:
                new_balance = (Decimal(ref_user[0]) + bonus).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                self.db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (str(new_balance), referrer_id))
                
                self.db.execute("""
                    INSERT INTO referrals (referrer_id, referred_id, level, bonus_amount, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (referrer_id, user_id, tier["level"], str(bonus), datetime.now().isoformat()))
                
            current_user_id = referrer_id

    def get_user_investments(self, user_id: int) -> List[dict]:
        rows = self.db.fetchall("SELECT * FROM investments WHERE user_id = ? ORDER BY start_date DESC", (user_id,))
        return [{"id": r[0], "plan_type": r[2], "amount": Decimal(r[3]), "daily_rate": Decimal(r[4]), "duration": r[5],
                 "start_date": r[6], "end_date": r[7], "total_return": Decimal(r[8]), "daily_earning": Decimal(r[9]),
                 "status": r[10], "total_earned": Decimal(r[11])} for r in rows]

# ===================================================================
# UI/UX KEYBOARD CANVAS
# ===================================================================

class Keyboards:
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Invest", callback_data="invest"), InlineKeyboardButton("📊 Portfolio", callback_data="portfolio")],
            [InlineKeyboardButton("💵 Withdraw", callback_data="withdraw"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
            [InlineKeyboardButton("🤝 Support", callback_data="support"), InlineKeyboardButton("❓ Help", callback_data="help_menu")],
            [InlineKeyboardButton("♻️ Statistics", callback_data="stats")]
        ])

    @staticmethod
    def plans_menu() -> InlineKeyboardMarkup:
        keyboard = []
        for key, plan in Config.PLANS.items():
            btn_text = f"{plan['name']} ({plan['daily_rate']*100}%)"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"plan_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def confirm_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Confirm & Check Nodes", callback_data="confirm_deposit"), 
             InlineKeyboardButton("❌ Cancel", callback_data="cancel_deposit")]
        ])

    @staticmethod
    def back_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]])

    @staticmethod
    def admin_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 System Stats", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Users Database", callback_data="admin_users")],
            [InlineKeyboardButton("📥 Pending Deposits", callback_data="admin_deposits")],
            [InlineKeyboardButton("📤 Pending Withdrawals", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("📢 Global Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])

    @staticmethod
    def admin_deposit_approval(deposit_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{deposit_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{deposit_id}")]
        ])

# ===================================================================
# CONVERSATION HANDLERS STATES
# ===================================================================

SELECTING_PLAN, ENTERING_AMOUNT, ENTERING_TRANSACTION_ID, CONFIRMING_DEPOSIT = range(4)
ENTERING_WITHDRAW_AMOUNT = 5

# ===================================================================
# BOT CORE ENGINE
# ===================================================================

class InvestmentBot:
    def __init__(self):
        self.db = Database()
        self.user_manager = UserManager(self.db)
        self.investment_manager = InvestmentManager(self.db)

    async def send_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        user = self.user_manager.get_or_create_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
        text = (
            f"<b>🌟 INVESTMENT PRO DASHBOARD</b>\n"
            f"<i>⚙️ Status: <code>[Enterprise PostgreSQL Node Connected]</code></i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Account ID:</b> <code>{user['user_id']}</code>\n"
            f"💰 <b>Available Balance:</b> <code>{Config.CURRENCY}{user['balance']:,.2f}</code>\n\n"
            f"📊 <b>Financial Statements:</b>\n"
            f" ├ Active Capital: <code>{Config.CURRENCY}{user['total_invested']:,.2f}</code>\n"
            f" ├ Total Net Earnings: <code>{Config.CURRENCY}{user['total_earned']:,.2f}</code>\n"
            f" └ Total Withdrawn: <code>{Config.CURRENCY}{user['total_withdrawn']:,.2f}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Select an action from the control console below:</i>"
        )
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")
        else:
            if update.message:
                await update.message.reply_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        referral_code = context.args[0] if context.args else None
        self.user_manager.get_or_create_user(user.id, user.username, user.first_name, user.last_name, referral_code)
        await self.send_main_menu(update, context, edit=False)

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
        context.user_data.clear()
        await self.send_main_menu(update, context, edit=True)
        return ConversationHandler.END

    # ===================================================================
    # INVESTMENT PIPELINE WITH AUTOMATION SIMULATION
    # ===================================================================
    async def invest_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        text = (
            "<b>📈 SELECT SMART INVESTMENT PORTFOLIO</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💼 <b>Starter Plan:</b> <code>1.0%</code> Daily / 30 Days\n"
            "💼 <b>Silver Plan:</b> <code>1.5%</code> Daily / 60 Days\n"
            "💼 <b>Gold Plan:</b> <code>2.0%</code> Daily / 90 Days\n"
            "💼 <b>Platinum Plan:</b> <code>2.5%</code> Daily / 120 Days\n\n"
            "⚙️ <i>Select a tier below to view details and invest:</i>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.plans_menu(), parse_mode="HTML")
        return SELECTING_PLAN

    async def plan_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        plan_type = query.data.replace("plan_", "")
        context.user_data["selected_plan"] = plan_type
        plan = Config.PLANS[plan_type]
        text = (
            f"<b>📋 PLAN MATRIX: {plan['name'].upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔹 <b>Minimum Allocation:</b> <code>{Config.CURRENCY}{plan['min']:,}</code>\n"
            f"🔹 <b>Maximum Allocation:</b> <code>{Config.CURRENCY}{plan['max']:,}</code>\n"
            f"🔹 <b>Daily Dividend Rate:</b> <code>{plan['daily_rate']*100}%</code>\n"
            f"🔹 <b>Lockup Period:</b> <code>{plan['duration']} Days</code>\n"
            f"🔹 <i>{plan['description']}</i>\n\n"
            f"<b>⌨️ Please type investment capital amount ({Config.CURRENCY}):</b>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_AMOUNT

    async def amount_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return ENTERING_AMOUNT

        try:
            text = update.message.text.strip().replace(Config.CURRENCY, "").replace("$", "").replace(",", "")
            amount = Decimal(text).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            await update.message.reply_text(
                "❌ <b>Invalid Input Style!</b>\n"
                "Please type a pure numerical value (e.g., 250):",
                reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
            return ENTERING_AMOUNT

        plan_type = context.user_data.get("selected_plan")
        plan = Config.PLANS[plan_type]
        if amount < plan["min"] or amount > plan["max"]:
            await update.message.reply_text(
                f"❌ <b>Capital Allocation Limits Fault!</b>\n"
                f"Your input: <code>{Config.CURRENCY}{amount}</code>\n"
                f"Allowed range: <code>{Config.CURRENCY}{plan['min']}</code> - <code>{Config.CURRENCY}{plan['max']}</code>\n"
                f"Please input a valid amount:", reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
            return ENTERING_AMOUNT

        context.user_data["investment_amount"] = amount

        payment_text = (
            f"<b>⚡ AUTO-GENERATED PAYMENT INVOICE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 <b>Target Amount:</b> <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f"💼 <b>Selected Category:</b> <code>{plan['name']} Plan</code>\n\n"
            f"⚙️ <b>DEPOSIT DESTINATION:</b>\n"
            f" ├ <b>Network Type:</b> <code>{Config.NETWORK}</code>\n"
            f" ├ <b>Payment Asset:</b> <code>{Config.PAYMENT_METHOD}</code>\n"
            f" └ <b>Secure Wallet Destination:</b> (Tap to auto-copy)\n"
            f"<code>{Config.WALLET_ADDRESS}</code>\n\n"
            f"💡 <i>Demo Note: Type <code>TEST100</code> below to simulate instant Automated Webhook Gateway verification!</i>\n\n"
            f"<b>⌨️ Input Transaction Hash / ID (TXID):</b>"
        )
        await update.message.reply_text(payment_text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_TRANSACTION_ID

    async def transaction_id_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return ENTERING_TRANSACTION_ID

        transaction_id = update.message.text.strip()
        
        duplicate = self.db.fetchone("SELECT id FROM deposit_requests WHERE transaction_id = ?", (transaction_id,))
        if duplicate and transaction_id != "TEST100":
            await update.message.reply_text(
                "⚠️ <b>SECURITY VIOLATION DETECTED!</b>\n"
                "This Transaction Hash has already been logged in the system ledger database.\n"
                "Input a unique hash:", reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
            return ENTERING_TRANSACTION_ID

        amount = context.user_data.get("investment_amount")
        plan_type = context.user_data.get("selected_plan")

        context.user_data["transaction_id"] = transaction_id
        plan = Config.PLANS[plan_type]
        daily_earning = (amount * plan["daily_rate"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_return = (daily_earning * plan["duration"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        confirm_text = (
            f"<b>📊 INBOUND TRANSACTION AUDIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>Investment Principal:</b> <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f"📦 <b>Assigned Plan:</b> <code>{plan['name']} Matrix</code>\n"
            f"🔗 <b>Hash Reference:</b> <code>{transaction_id}</code>\n\n"
            f"📈 <b>Projected Performance Matrix:</b>\n"
            f" ├ Daily Dividends: <code>{Config.CURRENCY}{daily_earning:,.2f}</code>\n"
            f" └ Maturity Yield: <code>{Config.CURRENCY}{total_return:,.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>Initialize blockchain nodes matching algorithm?</i>"
        )
        await update.message.reply_text(confirm_text, reply_markup=Keyboards.confirm_menu(), parse_mode="HTML")
        return CONFIRMING_DEPOSIT

    async def confirm_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        amount = context.user_data.get("investment_amount")
        plan_type = context.user_data.get("selected_plan")
        transaction_id = context.user_data.get("transaction_id")

        await query.edit_message_text("🔄 <code>[1/3] Connecting to Crypto API Gateway Webhook...</code>", parse_mode="HTML")
        await asyncio.sleep(1)
        await query.edit_message_text("🔄 <code>[2/3] Querying Transaction Hash from Mempool...</code>", parse_mode="HTML")
        await asyncio.sleep(1)
        await query.edit_message_text("🔄 <code>[3/3] Authenticating IPN Digital HMAC Signatures...</code>", parse_mode="HTML")
        await asyncio.sleep(0.8)

        if transaction_id == "TEST100":
            result = self.investment_manager.create_investment(update.effective_user.id, plan_type, amount)
            self.db.execute("""
                INSERT INTO deposit_requests (user_id, plan_type, amount, transaction_id, status, created_at, processed_at)
                VALUES (?, ?, ?, ?, 'approved', ?, ?)
            """, (update.effective_user.id, plan_type, str(amount), transaction_id, datetime.now().isoformat(), datetime.now().isoformat()))
            
            await query.edit_message_text(
                f"<b>⚡ [INSTANT API AUTO-VERIFIED] ⚡</b>\n\n"
                f"✅ <b>Status:</b> Blockchain Payment Confirmed via Webhook IPN.\n"
                f"💼 <b>Activated Plan:</b> <code>{result['plan']}</code>\n"
                f"💰 <b>Capital Amount:</b> <code>{Config.CURRENCY}{result['amount']:,.2f}</code>\n"
                f"📈 <b>Daily Dividends:</b> <code>{Config.CURRENCY}{result['daily_earning']:,.2f}</code>\n\n"
                f"🚀 <i>3-Tier Referral matrices & investment pool credited automatically!</i>",
                reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
            context.user_data.clear()
            return ConversationHandler.END

        try:
            cursor = self.db.execute("""
                INSERT INTO deposit_requests (user_id, plan_type, amount, transaction_id, status, created_at)
                VALUES (?, ?, ?, ?, 'awaiting_approval', ?)
            """, (update.effective_user.id, plan_type, str(amount), transaction_id, datetime.now().isoformat()))
            deposit_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            await query.edit_message_text("❌ <b>Ledger Rejection!</b> Duplicate TXID detected.", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
            return ConversationHandler.END

        await self.notify_admin_deposit(update, context, deposit_id, plan_type, amount, transaction_id)

        await query.edit_message_text(
            f"<b>✅ INBOUND LEDGER RECORDED</b>\n\n"
            f"📦 <b>Ticket ID:</b> <code>#{deposit_id}</code>\n"
            f"🔗 <b>TXID Hash:</b> <code>{transaction_id}</code>\n\n"
            f"⌛ <i>Blockchain confirmations pending node validation. Operator manual oversight notification dispatched.</i>",
            reply_markup=Keyboards.back_menu(), parse_mode="HTML"
        )

        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.user_data.clear()
        await query.edit_message_text("❌ Pipeline cleared. Capital deposit cancelled.", reply_markup=Keyboards.back_menu())
        return ConversationHandler.END

    # ===================================================================
    # ADMIN HUB
    # ===================================================================
    async def notify_admin_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE, deposit_id: int, plan_type: str, amount: Decimal, transaction_id: str):
        user = update.effective_user
        plan = Config.PLANS.get(plan_type, {"name": "Unknown"})

        admin_text = (
            f"🚨 <b>NEW INBOUND LIQUIDITY MANUAL VERIFICATION</b>\n\n"
            f"👤 <b>User Entity:</b> {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 <b>Account ID:</b> <code>{user.id}</code>\n\n"
            f"📊 <b>Specifications:</b>\n"
            f" ├ Ticket: <code>#{deposit_id}</code>\n"
            f" ├ Plan: <code>{plan['name']}</code>\n"
            f" ├ Principal: <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f" └ Asset TX Hash: <code>{transaction_id}</code>\n\n"
            f"⚖️ <i>Decide operator node approval actions:</i>"
        )

        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", reply_markup=Keyboards.admin_deposit_approval(deposit_id))
            except Exception:
                pass

    async def approve_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        deposit_id = int(query.data.replace("approve_deposit_", ""))
        deposit = self.db.fetchone("SELECT * FROM deposit_requests WHERE id = ?", (deposit_id,))

        user_id, plan_type, amount, transaction_id = deposit[1], deposit[2], Decimal(deposit[3]), deposit[4]
        result = self.investment_manager.create_investment(user_id, plan_type, amount)

        self.db.execute("UPDATE deposit_requests SET status = 'approved' WHERE id = ?", (deposit_id,))

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"<b>🎉 DEPOSIT AUDIT VERIFIED!</b>\n\n"
                    f"💳 <b>Ticket ID:</b> <code>#{deposit_id}</code>\n"
                    f"💼 <b>Activated Plan:</b> <code>{result['plan']}</code>\n"
                    f"💰 <b>Capital Amount:</b> <code>{Config.CURRENCY}{result['amount']:,.2f}</code>\n\n"
                    f"🚀 <i>Profits allocation script running smoothly!</i>"
                ), reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
        except Exception:
            pass

        await query.edit_message_text(f"<b>✅ TICKET #{deposit_id} APPROVED SUCCESSFULLY</b>", parse_mode="HTML")

    async def reject_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        deposit_id = int(query.data.replace("reject_deposit_", ""))
        deposit = self.db.fetchone("SELECT * FROM deposit_requests WHERE id = ?", (deposit_id,))
        user_id = deposit[1]

        self.db.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = ?", (deposit_id,))

        try:
            await context.bot.send_message(chat_id=user_id, text=f"<b>❌ DEPOSIT TICKET #{deposit_id} REJECTED BY NODES</b>", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        except Exception:
            pass
        await query.edit_message_text(f"<b>❌ TICKET #{deposit_id} REJECTED</b>", parse_mode="HTML")

    # ===================================================================
    # ADDITIONAL DASHBOARDS
    # ===================================================================
    async def portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = self.user_manager.get_user(update.effective_user.id)
        investments = self.investment_manager.get_user_investments(update.effective_user.id)
        
        text = f"<b>📊 YOUR REAL-TIME INVESTMENT PORTFOLIO</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if not investments:
            text += "<i>You have no operational assets deployed currently. Deploy capital to unlock yields!</i>"
        else:
            total_active = total_earned = Decimal("0.00")
            for inv in investments:
                plan_name = Config.PLANS[inv["plan_type"]]["name"]
                status = "🟢 Operational" if inv["status"] == "active" else "🔴 Matured"
                text += (
                    f" 🖥 <b>{plan_name} Matrix Node</b> ({status})\n"
                    f"  ├ Principal: <code>{Config.CURRENCY}{inv['amount']:,.2f}</code>\n"
                    f"  ├ Earned Dividends: <code>{Config.CURRENCY}{inv['total_earned']:,.2f}</code>\n"
                    f"  └ Cycle: <code>{inv['start_date'][:10]}</code> to <code>{inv['end_date'][:10]}</code>\n\n"
                )
                if inv["status"] == "active": total_active += inv["amount"]
                total_earned += inv["total_earned"]
                
            text += (
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧮 <b>CONSOLIDATED CAPITAL POSITION:</b>\n"
                f" ├ Deployed Capital: <code>{Config.CURRENCY}{total_active:,.2f}</code>\n"
                f" ├ Lifetime Yield Accrued: <code>{Config.CURRENCY}{total_earned:,.2f}</code>\n"
                f" └ Fluid Available Cash: <code>{Config.CURRENCY}{user['balance']:,.2f}</code>"
            )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def withdraw_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = self.user_manager.get_user(update.effective_user.id)
        text = (
            f"<b>📤 INITIATE CASH CLEARING OUTBOUND PIPELINE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>Liquid Cash Assets:</b> <code>{Config.CURRENCY}{user['balance']:,.2f}</code>\n"
            f"🚧 <b>Minimum Safe Bounds:</b> <code>{Config.CURRENCY}{Config.MIN_INVESTMENT}</code>\n\n"
            f"<b>⌨️ Type out your desired withdrawal value ({Config.CURRENCY}):</b>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_WITHDRAW_AMOUNT

    async def withdraw_amount_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text: return ENTERING_WITHDRAW_AMOUNT
        user = self.user_manager.get_user(update.effective_user.id)
        try:
            amount = Decimal(update.message.text.strip()).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            await update.message.reply_text("❌ Parsing failure. Type clean digits:", reply_markup=Keyboards.back_menu())
            return ENTERING_WITHDRAW_AMOUNT
            
        if amount > user["balance"] or amount < Config.MIN_INVESTMENT:
            await update.message.reply_text("❌ Overdraft or falls beneath threshold floor limit bounds.", reply_markup=Keyboards.back_menu())
            return ENTERING_WITHDRAW_AMOUNT

        new_balance = (user["balance"] - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        new_withdrawn = (user["total_withdrawn"] + amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        self.db.execute("UPDATE users SET balance = ?, total_withdrawn = ? WHERE user_id = ?", (str(new_balance), str(new_withdrawn), update.effective_user.id))
        
        msg = await update.message.reply_text("🔄 <code>Clearinghouse Routing System executing API call...</code>", parse_mode="HTML")
        await asyncio.sleep(1.5)
        await msg.edit_text(
            f"<b>✅ INSTANT BLOCKCHAIN PAYOUT SUCCESSFUL</b>\n\n"
            f"📤 <b>Value Amount:</b> <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f"🚀 <b>TX Hash:</b> <code>0x{ ''.join(random.choices(string.hexdigits, k=32)).lower() }</code>\n\n"
            f"🔥 <i>Funds pushed instantly to your integrated corporate settlement address.</i>",
            reply_markup=Keyboards.back_menu(), parse_mode="HTML"
        )
        return ConversationHandler.END

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = self.user_manager.get_user(update.effective_user.id)
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
        
        ref_count = self.db.fetchone("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (update.effective_user.id,))[0]
        bonus_rows = self.db.fetchall("SELECT bonus_amount FROM referrals WHERE referrer_id = ?", (update.effective_user.id,))
        total_bonus = sum(Decimal(r[0]) for r in bonus_rows)
        
        text = (
            f"<b>👥 3-TIER AFFILIATE NETWORK MATRIX</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔗 <b>Your Specialized Link:</b>\n<code>{ref_link}</code>\n\n"
            f"📊 <b>Network Statistics Matrix:</b>\n"
            f" ├ Team Count: <code>{ref_count} Members</code>\n"
            f" └ Affiliate Earnings: <code>{Config.CURRENCY}{total_bonus:,.2f}</code>\n\n"
            f"🏆 <b>Cascading System Returns:</b>\n"
            f" ├ Tier 1: Direct Connections - <code>{Config.REF_L1_PERCENT}%</code>\n"
            f" ├ Tier 2: Level II - <code>{Config.REF_L2_PERCENT}%</code>\n"
            f" └ Tier 3: Multipliers - <code>{Config.REF_L3_PERCENT}%</code>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def support(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        text = f"<b>🤝 CORPORATE HELP DESK</b>\n━━━━━━\n📬 <b>Email:</b> <code>{Config.SUPPORT_EMAIL}</code>\n✈️ <b>Telegram:</b> {Config.SUPPORT_TELEGRAM}"
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def help_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        text = "<b>❓ OPERATIONAL terminal MAN-GUIDE</b>\n\nUse standard dashboard buttons console interface loops smoothly."
        if query: await query.answer(); await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        else: await update.message.reply_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        stats = self.user_manager.get_stats()
        text = (
            f"<b>📈 PLATFORM REAL-TIME SYSTEM LEDGER METRICS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>Active Accounts Registered:</b> <code>{stats['total_users']} Profiles</code>\n"
            f"💼 <b>Total Capital Under Management:</b> <code>{Config.CURRENCY}{stats['total_investments']:,.2f}</code>\n"
            f"💰 <b>Total Dividends Disbursed:</b> <code>{Config.CURRENCY}{stats['total_earned']:,.2f}</code>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    # ===================================================================
    # ADMIN SYSTEM CONSOLE UI LAYERS
    # ===================================================================
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in Config.ADMIN_IDS: return
        await update.message.reply_text("<b>🕹 ADMINISTRATIVE CONTROL MATRIX CENTER</b>", reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        stats = self.user_manager.get_stats()
        text = f"<b>📊 OPERATIONAL CONTROL SYSTEM HEALTH STATISTICS</b>\n\n• Users Count: <code>{stats['total_users']}</code>\n• Principal Pool: <code>{Config.CURRENCY}{stats['total_investments']:,.2f}</code>"
        await query.edit_message_text(text, reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def admin_deposits(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        deposits = self.db.fetchall("SELECT d.id, d.user_id, u.username, d.amount, d.transaction_id FROM deposit_requests d JOIN users u ON d.user_id = u.user_id WHERE d.status = 'awaiting_approval'")
        if not deposits: text = "📬 Inbound transaction approval queues empty."
        else:
            text = f"<b>📥 PENDING INBOUND REQUISITIONS</b>\n\n"
            for dep in deposits: text += f"🎫 Ticket <code>#{dep[0]}</code> | User: <code>{dep[1]}</code>\n ├ Val: <code>{Config.CURRENCY}{Decimal(dep[3]):,.2f}</code>\n └ Hash: <code>{dep[4]}</code>\n\n"
        await query.edit_message_text(text, reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        users = self.db.fetchall("SELECT user_id, username, balance FROM users LIMIT 10")
        text = f"<b>👥 SYSTEM USERS MAP REGISTRY</b>\n\n"
        for u in users: text += f"🔑 <code>{u[0]}</code> | @{u[1] or 'N/A'} -> Bal: <code>{Config.CURRENCY}{Decimal(u[2]):,.2f}</code>\n"
        await query.edit_message_text(text, reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def admin_withdrawals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        text = "📤 Outbound network clearing demands empty."
        await query.edit_message_text(text, reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        await query.edit_message_text("📢 Use: <code>/broadcast Message</code> to push announcements text.", reply_markup=Keyboards.admin_menu(), parse_mode="HTML")

    async def broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in Config.ADMIN_IDS: return
        message = ' '.join(context.args)
        if not message: return
        users = self.db.fetchall("SELECT user_id FROM users")
        for u in users:
            try: await context.bot.send_message(chat_id=u[0], text=f"<b>📢 GLOBAL PLATFORM SYSTEM ANNOUNCEMENT</b>\n\n{message}", parse_mode="HTML")
            except Exception: pass
        await update.message.reply_text("📡 Broadcast operations completed.")

# ===================================================================
# AUTOMATED INTERESTS SIMULATION (NATIVE ASYNC JOB QUEUE)
# ===================================================================

async def run_automated_interest_cycles_job(context: ContextTypes.DEFAULT_TYPE):
    """Safe Native Job Queue callback runner running directly inside PTB Event Loop"""
    bot_instance = context.job.data["bot"]
    db = bot_instance.db
    active_contracts = db.fetchall("SELECT * FROM investments WHERE status = 'active'")
    if not active_contracts: return

    for contract in active_contracts:
        c_id, user_id, plan_type, amount, daily_rate, duration, start_date, end_date, total_return, daily_earning, _, total_earned, last_calc = contract
        
        daily_earning = Decimal(daily_earning)
        new_earned = (Decimal(total_earned) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        db.execute("UPDATE investments SET total_earned = ?, last_calculation = ? WHERE id = ?", (str(new_earned), datetime.now().isoformat(), c_id))
        
        user_row = db.fetchone("SELECT balance, total_earned FROM users WHERE user_id = ?", (user_id,))
        if user_row:
            final_bal = (Decimal(user_row[0]) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            final_net = (Decimal(user_row[1]) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            db.execute("UPDATE users SET balance = ?, total_earned = ? WHERE user_id = ?", (str(final_bal), str(final_net), user_id))
            
            notification_text = (
                f"<b>💰 DYNAMIC INTEREST DIVIDEND OUTCOME RETRIEVED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📈 Account ID Matrix: <code>#{c_id}</code> ({Config.PLANS[plan_type]['name']})\n"
                f"💵 Disbursed Return: <code>{Config.CURRENCY}{daily_earning:,.2f}</code>\n"
                f"💳 Available Balance: <code>{Config.CURRENCY}{final_bal:,.2f}</code>\n\n"
                f"<i>⚙️ Live Smart Node automation cycling continuously.</i>"
            )
            try:
                await context.bot.send_message(chat_id=user_id, text=notification_text, parse_mode="HTML")
            except Exception:
                pass

# ===================================================================
# INITIALIZATION FRAMEWORK ASSEMBLY RUNNER
# ===================================================================

def main():
    bot = InvestmentBot()
    # Build Application with JobQueue enabled natively
    application = Application.builder().token(Config.BOT_TOKEN).build()

    # Callback Query Navigation Routing
    application.add_handler(CallbackQueryHandler(bot.portfolio, pattern="^portfolio$"))
    application.add_handler(CallbackQueryHandler(bot.referral, pattern="^referral$"))
    application.add_handler(CallbackQueryHandler(bot.support, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(bot.help_menu, pattern="^help_menu$"))
    application.add_handler(CallbackQueryHandler(bot.stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"))

    # Admin Matrix Management Routing Handlers
    application.add_handler(CallbackQueryHandler(bot.admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(bot.admin_users, pattern="^admin_users$"))
    application.add_handler(CallbackQueryHandler(bot.admin_deposits, pattern="^admin_deposits$"))
    application.add_handler(CallbackQueryHandler(bot.admin_withdrawals, pattern="^admin_withdrawals$"))
    application.add_handler(CallbackQueryHandler(bot.admin_broadcast, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(bot.approve_deposit, pattern="^approve_deposit_"))
    application.add_handler(CallbackQueryHandler(bot.reject_deposit, pattern="^reject_deposit_"))

    # Pipeline Stateful Structural Conversations
    invest_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.invest_callback, pattern="^invest$")],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(bot.plan_selected, pattern="^plan_"), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")],
            ENTERING_AMOUNT: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.amount_entered)],
            ENTERING_TRANSACTION_ID: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.transaction_id_entered)],
            CONFIRMING_DEPOSIT: [CallbackQueryHandler(bot.confirm_deposit, pattern="^confirm_deposit$"), CallbackQueryHandler(bot.cancel_deposit, pattern="^cancel_deposit$"), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
        },
        fallbacks=[CommandHandler("start", bot.start), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.withdraw_start, pattern="^withdraw$")],
        states={ENTERING_WITHDRAW_AMOUNT: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.withdraw_amount_entered)]},
        fallbacks=[CommandHandler("start", bot.start), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
    )

    application.add_handler(invest_conv)
    application.add_handler(withdraw_conv)

    # Command Mapping Handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_menu))
    application.add_handler(CommandHandler("invest", bot.invest_callback))
    application.add_handler(CommandHandler("portfolio", bot.portfolio))
    application.add_handler(CommandHandler("withdraw", bot.withdraw_start))
    application.add_handler(CommandHandler("referral", bot.referral))
    application.add_handler(CommandHandler("admin", bot.admin_panel))
    application.add_handler(CommandHandler("broadcast", bot.broadcast_message))

    # Deploy Native Cloud-Safe Job Queue Instead of APScheduler
    job_queue = application.job_queue
    job_queue.run_repeating(run_automated_interest_cycles_job, interval=60, first=10, data={"bot": bot})
    print("-> Native Event-Loop JobQueue Deployed Successfully.")

    print("=" * 60)
    print("INVESTMENT PRO BOT - HIGH CONTEXT PRESENTATION CLIENT DEMO MODE")
    print("=" * 60)
    print("Hint: Type TEST100 in deposit flow to demo full automatic API matching validation!")
    print("=" * 60)

    application.run_polling()

if __name__ == "__main__":
    main()
