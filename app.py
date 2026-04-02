import os
import json
from datetime import date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ff-manager-secret-key-change-me-in-production'

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('Access denied. Admin only.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/register', methods=['GET', 'POST'])
def register():
    flash('Registration is by invitation only. Contact your administrator.', 'danger')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            if user.get('status') == 'suspended':
                flash('Your account has been suspended. Please contact your administrator.', 'danger')
                return render_template('Login.html')
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user.get('is_admin', False)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('Login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('change_password'))
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('change_password'))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT password FROM users WHERE id = %s', (session['user_id'],))
        user = cursor.fetchone()
        if not user or not check_password_hash(user['password'], current_password):
            flash('Current password is incorrect.', 'danger')
            conn.close()
            return redirect(url_for('change_password'))
        new_hashed = generate_password_hash(new_password)
        cursor.execute('UPDATE users SET password = %s WHERE id = %s', (new_hashed, session['user_id']))
        conn.commit()
        conn.close()
        flash('Password updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM stock WHERE user_id = %s', (user_id,))
    total_items = cursor.fetchone()['count']
    cursor.execute('SELECT SUM(quantity) FROM stock WHERE user_id = %s', (user_id,))
    total_quantity = cursor.fetchone()['sum'] or 0.0
    cursor.execute(
        'SELECT SUM((selling_price - unit_cost) * quantity) FROM stock WHERE user_id = %s AND quantity > 0',
        (user_id,)
    )
    result = cursor.fetchone()['sum']
    total_profit_potential = result or 0.0
    conn.close()
    return render_template('dashboard.html', total_items=total_items, total_quantity=total_quantity, total_profit_potential=total_profit_potential)

@app.route('/admin')
@admin_required
def admin_panel():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, status, is_admin FROM users ORDER BY id')
    users = cursor.fetchall()
    conn.close()
    return render_template('admin.html', users=users)

@app.route('/admin/create-user', methods=['POST'])
@admin_required
def admin_create_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin_panel'))
    hashed_password = generate_password_hash(password)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password, status, is_admin) VALUES (%s, %s, %s, %s)',
                      (username, hashed_password, 'active', False))
        conn.commit()
        flash(f'Account created for "{username}" successfully!', 'success')
    except Exception:
        conn.rollback()
        flash('Username already exists.', 'danger')
    finally:
        conn.close()
    return redirect(url_for('admin_panel'))

@app.route('/admin/suspend/<int:user_id>')
@admin_required
def admin_suspend(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET status = %s WHERE id = %s AND is_admin = FALSE', ('suspended', user_id))
    conn.commit()
    conn.close()
    flash('Account suspended.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/activate/<int:user_id>')
@admin_required
def admin_activate(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET status = %s WHERE id = %s', ('active', user_id))
    conn.commit()
    conn.close()
    flash('Account activated.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reset-password/<int:user_id>', methods=['POST'])
@admin_required
def admin_reset_password(user_id):
    new_password = request.form.get('new_password', '').strip()
    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin_panel'))
    hashed = generate_password_hash(new_password)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET password = %s WHERE id = %s', (hashed, user_id))
    conn.commit()
    conn.close()
    flash('Password reset successfully.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete/<int:user_id>')
@admin_required
def admin_delete(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = %s AND is_admin = FALSE', (user_id,))
    conn.commit()
    conn.close()
    flash('Account deleted permanently.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/get_products')
@login_required
def get_products():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, item_name, quantity, unit_cost, selling_price FROM stock WHERE user_id = %s AND quantity > 0 ORDER BY item_name',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    products = [{'id': r['id'], 'name': r['item_name'], 'stock': r['quantity'],
                 'price': r['selling_price'], 'cost': r['unit_cost']} for r in rows]
    return jsonify({'products': products})

@app.route('/record_sale', methods=['POST'])
@login_required
def record_sale():
    user_id = session['user_id']
    data = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({'status': 'error', 'message': 'No items in sale.'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        total_amount = 0.0
        items_sold_details = []
        for item in items:
            item_id = item['id']
            qty_sold = float(item['quantity'])
            price = float(item['price'])
            cursor.execute('SELECT quantity, item_name FROM stock WHERE id = %s AND user_id = %s', (item_id, user_id))
            row = cursor.fetchone()
            if not row:
                return jsonify({'status': 'error', 'message': f'Item ID {item_id} not found.'}), 400
            if row['quantity'] < qty_sold:
                return jsonify({'status': 'error', 'message': f'Not enough stock for "{row["item_name"]}".'}), 400
            cursor.execute('UPDATE stock SET quantity = quantity - %s WHERE id = %s AND user_id = %s', (qty_sold, item_id, user_id))
            subtotal = qty_sold * price
            total_amount += subtotal
            items_sold_details.append({'name': row['item_name'], 'qty': qty_sold, 'price': price, 'subtotal': subtotal})
        today = date.today().isoformat()
        cursor.execute('INSERT INTO sales (user_id, total_amount, sale_date, items_sold) VALUES (%s, %s, %s, %s)',
                     (user_id, total_amount, today, json.dumps(items_sold_details)))
        conn.commit()
        return jsonify({'status': 'success', 'total': total_amount})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/stock', methods=['GET', 'POST'])
@login_required
def stock():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        delete_id = request.form.get('delete_id')
        if delete_id:
            cursor.execute('DELETE FROM stock WHERE id = %s AND user_id = %s', (delete_id, user_id))
            conn.commit()
            flash('Item deleted successfully.', 'success')
            conn.close()
            return redirect(url_for('stock'))

        edit_id = request.form.get('edit_id')
        if edit_id:
            item_name = request.form.get('item_name', '').strip()
            quantity = float(request.form.get('quantity', 0))
            unit_cost = float(request.form.get('unit_cost', 0))
            selling_price = float(request.form.get('selling_price', 0))
            if quantity < 0 or unit_cost < 0 or selling_price < 0:
                flash('Values cannot be negative.', 'danger')
                conn.close()
                return redirect(url_for('stock'))
            cursor.execute(
                'UPDATE stock SET item_name=%s, quantity=%s, unit_cost=%s, selling_price=%s WHERE id=%s AND user_id=%s',
                (item_name, quantity, unit_cost, selling_price, edit_id, user_id)
            )
            conn.commit()
            flash(f'Item "{item_name}" updated successfully.', 'success')
            conn.close()
            return redirect(url_for('stock'))

        item_name = request.form.get('item_name', '').strip()
        quantity = float(request.form.get('quantity', 0))
        unit_cost = float(request.form.get('unit_cost', 0))
        selling_price = float(request.form.get('selling_price', 0))

        if quantity <= 0 or selling_price < 0:
            flash('Invalid quantity or selling price.', 'danger')
            conn.close()
            return redirect(url_for('stock'))

        cursor.execute(
            'SELECT id, quantity FROM stock WHERE user_id=%s AND item_name=%s',
            (user_id, item_name)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                'UPDATE stock SET quantity=%s, unit_cost=%s, selling_price=%s WHERE id=%s AND user_id=%s',
                (existing['quantity'] + quantity, unit_cost, selling_price, existing['id'], user_id)
            )
            flash(f'Stock replenished for "{item_name}".', 'success')
        else:
            cursor.execute(
                'INSERT INTO stock (user_id, item_name, quantity, unit_cost, selling_price) VALUES (%s,%s,%s,%s,%s)',
                (user_id, item_name, quantity, unit_cost, selling_price)
            )
            flash(f'New item "{item_name}" added to stock.', 'success')
        conn.commit()

    cursor.execute(
        'SELECT id, item_name, quantity, unit_cost, selling_price FROM stock WHERE user_id=%s ORDER BY item_name',
        (user_id,)
    )
    stock_items = cursor.fetchall()
    total_inventory_value = sum(item['quantity'] * item['selling_price'] for item in stock_items)
    total_units = sum(item['quantity'] for item in stock_items)
    conn.close()
    return render_template('Stock.html', stock=stock_items,
                           total_inventory_value=total_inventory_value,
                           total_units=total_units)

@app.route('/profit_accumulator')
@login_required
def profit_accumulator():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, item_name, quantity, unit_cost, selling_price FROM stock WHERE user_id=%s ORDER BY item_name', (user_id,))
    stock_data = cursor.fetchall()
    conn.close()
    inventory_analysis = []
    total_potential_profit = 0.0
    for item in stock_data:
        d = dict(item)
        qty, cost, sp = d['quantity'], d['unit_cost'], d.get('selling_price', 0.0) or 0.0
        ppu = sp - cost
        margin = (ppu / sp * 100) if sp > 0 else 0.0
        itp = ppu * qty if qty > 0 else 0.0
        if qty > 0: total_potential_profit += itp
        inventory_analysis.append({'id': d['id'], 'name': d['item_name'], 'qty': qty, 'cost': cost,
                                    'selling_price': sp, 'profit_per_unit': ppu, 'margin_percent': margin, 'item_total_profit': itp})
    return render_template('profit_accumulator.html', inventory=inventory_analysis, total_potential_profit=total_potential_profit)

@app.route('/update_selling_price', methods=['POST'])
@login_required
def update_selling_price():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE stock SET selling_price=%s WHERE id=%s AND user_id=%s',
                 (float(request.form.get('selling_price', 0)), request.form.get('id'), user_id))
    conn.commit()
    conn.close()
    flash('Selling price updated.', 'success')
    return redirect(url_for('profit_accumulator'))

@app.route('/update_original_cost', methods=['POST'])
@login_required
def update_original_cost():
    user_id = session['user_id']
    new_cost = float(request.form.get('original_cost', 0))
    if new_cost < 0:
        flash('Cost cannot be negative.', 'danger')
        return redirect(url_for('profit_accumulator'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE stock SET unit_cost=%s WHERE id=%s AND user_id=%s',
                 (new_cost, request.form.get('id'), user_id))
    conn.commit()
    conn.close()
    flash('Original cost updated.', 'success')
    return redirect(url_for('profit_accumulator'))

@app.route('/payables', methods=['GET', 'POST'])
@login_required
def payables():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        pid = request.form.get('id', '').strip()
        supplier = request.form.get('supplier', '').strip()
        amount = float(request.form.get('amount', 0))
        tx_date = request.form.get('transaction_date', '')
        if not supplier or amount <= 0 or not tx_date:
            flash('All fields are required.', 'danger')
            conn.close()
            return redirect(url_for('payables'))
        if pid:
            cursor.execute('UPDATE payables SET supplier=%s, remaining_amount=%s, due_date=%s WHERE id=%s AND user_id=%s',
                         (supplier, amount, tx_date, pid, user_id))
            flash('Payable updated.', 'success')
        else:
            cursor.execute('INSERT INTO payables (user_id, supplier, original_amount, remaining_amount, due_date) VALUES (%s,%s,%s,%s,%s)',
                         (user_id, supplier, amount, amount, tx_date))
            flash('Payable recorded.', 'success')
        conn.commit()
        conn.close()
        return redirect(url_for('payables'))
    cursor.execute('SELECT id, supplier, original_amount, remaining_amount, due_date FROM payables WHERE user_id=%s ORDER BY due_date DESC', (user_id,))
    rows = cursor.fetchall()
    payables_list = []
    cleared_payables_list = []
    total_payables_calc = 0.0
    for r in rows:
        rem = r['remaining_amount']
        cursor.execute('SELECT MAX(transaction_date) as latest FROM transactions WHERE payable_id=%s', (r['id'],))
        latest = cursor.fetchone()
        display_date = latest['latest'] if latest and latest['latest'] else r['due_date']
        if rem > 0.005:
            total_payables_calc += rem
            payables_list.append({'id': r['id'], 'supplier': r['supplier'], 'original_amount': r['original_amount'],
                                   'amount': rem, 'transaction_date': display_date, 'status': 'Outstanding'})
        else:
            cleared_payables_list.append({'id': r['id'], 'supplier': r['supplier'], 'original_amount': r['original_amount'],
                                          'amount': rem, 'transaction_date': display_date, 'status': 'Paid'})
    conn.close()
    return render_template('Payables.html', payables=payables_list, cleared_payables=cleared_payables_list, total_payables_calc=total_payables_calc)

@app.route('/delete_Payables', methods=['POST'])
@login_required
def delete_Payables():
    user_id = session['user_id']
    pid = request.form.get('id')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM transactions WHERE payable_id=%s', (pid,))
    cursor.execute('DELETE FROM payables WHERE id=%s AND user_id=%s', (pid, user_id))
    conn.commit()
    conn.close()
    flash('Payable deleted.', 'success')
    return redirect(url_for('payables'))

@app.route('/receivables', methods=['GET', 'POST'])
@login_required
def receivables():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        rid = request.form.get('id', '').strip()
        customer = request.form.get('customer', '').strip()
        amount = float(request.form.get('amount', 0))
        tx_date = request.form.get('transaction_date', '')
        if not customer or amount <= 0 or not tx_date:
            flash('All fields are required.', 'danger')
            conn.close()
            return redirect(url_for('receivables'))
        if rid:
            cursor.execute('UPDATE receivables SET customer=%s, remaining_amount=%s, due_date=%s WHERE id=%s AND user_id=%s',
                         (customer, amount, tx_date, rid, user_id))
            flash('Receivable updated.', 'success')
        else:
            cursor.execute('INSERT INTO receivables (user_id, customer, original_amount, remaining_amount, due_date) VALUES (%s,%s,%s,%s,%s)',
                         (user_id, customer, amount, amount, tx_date))
            flash('Receivable recorded.', 'success')
        conn.commit()
        conn.close()
        return redirect(url_for('receivables'))
    cursor.execute('SELECT id, customer, original_amount, remaining_amount, due_date FROM receivables WHERE user_id=%s ORDER BY due_date DESC', (user_id,))
    rows = cursor.fetchall()
    receivables_list = []
    cleared_receivables_list = []
    total_receivables_calc = 0.0
    for r in rows:
        rem = r['remaining_amount']
        cursor.execute('SELECT MAX(transaction_date) as latest FROM transactions WHERE receivable_id=%s', (r['id'],))
        latest = cursor.fetchone()
        display_date = latest['latest'] if latest and latest['latest'] else r['due_date']
        if rem > 0.005:
            total_receivables_calc += rem
            receivables_list.append({'id': r['id'], 'customer': r['customer'], 'original_amount': r['original_amount'],
                                      'amount': rem, 'transaction_date': display_date, 'status': 'Outstanding'})
        else:
            cleared_receivables_list.append({'id': r['id'], 'customer': r['customer'], 'original_amount': r['original_amount'],
                                              'amount': rem, 'transaction_date': display_date, 'status': 'Collected'})
    conn.close()
    return render_template('Receivables.html', receivables=receivables_list, cleared_receivables=cleared_receivables_list, total_receivables_calc=total_receivables_calc)

@app.route('/delete_Receivables', methods=['POST'])
@login_required
def delete_Receivables():
    user_id = session['user_id']
    rid = request.form.get('id')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM transactions WHERE receivable_id=%s', (rid,))
    cursor.execute('DELETE FROM receivables WHERE id=%s AND user_id=%s', (rid, user_id))
    conn.commit()
    conn.close()
    flash('Receivable deleted.', 'success')
    return redirect(url_for('receivables'))

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    user_id = session['user_id']
    data = request.get_json()
    entity_id = int(data.get('entity_id'))
    entity_type = data.get('entity_type')
    amount = float(data.get('amount', 0))
    tx_date = data.get('date', date.today().isoformat())
    tx_type = data.get('transaction_type')
    description = data.get('description', '')
    if amount <= 0:
        return jsonify({'status': 'error', 'message': 'Amount must be positive.'}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if entity_type == 'payable':
            cursor.execute('SELECT remaining_amount FROM payables WHERE id=%s AND user_id=%s', (entity_id, user_id))
            row = cursor.fetchone()
            if not row: return jsonify({'status': 'error', 'message': 'Not found.'}), 404
            new_bal = (row['remaining_amount'] - amount) if tx_type == 'payment' else (row['remaining_amount'] + amount)
            cursor.execute('UPDATE payables SET remaining_amount=%s WHERE id=%s', (new_bal, entity_id))
            signed = amount if tx_type == 'payment' else -amount
            cursor.execute('INSERT INTO transactions (user_id, payable_id, amount, transaction_date, description) VALUES (%s,%s,%s,%s,%s)',
                         (user_id, entity_id, signed, tx_date, description))
        else:
            cursor.execute('SELECT remaining_amount FROM receivables WHERE id=%s AND user_id=%s', (entity_id, user_id))
            row = cursor.fetchone()
            if not row: return jsonify({'status': 'error', 'message': 'Not found.'}), 404
            new_bal = (row['remaining_amount'] - amount) if tx_type == 'payment' else (row['remaining_amount'] + amount)
            cursor.execute('UPDATE receivables SET remaining_amount=%s WHERE id=%s', (new_bal, entity_id))
            signed = amount if tx_type == 'payment' else -amount
            cursor.execute('INSERT INTO transactions (user_id, receivable_id, amount, transaction_date, description) VALUES (%s,%s,%s,%s,%s)',
                         (user_id, entity_id, signed, tx_date, description))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/history/<entity_type>/<int:entity_id>')
@login_required
def history(entity_type, entity_id):
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    if entity_type == 'payable':
        cursor.execute('SELECT supplier as name, original_amount, remaining_amount FROM payables WHERE id=%s AND user_id=%s', (entity_id, user_id))
        entity = cursor.fetchone()
        cursor.execute('SELECT id, amount, transaction_date, description FROM transactions WHERE payable_id=%s ORDER BY transaction_date ASC', (entity_id,))
        txs = cursor.fetchall()
    else:
        cursor.execute('SELECT customer as name, original_amount, remaining_amount FROM receivables WHERE id=%s AND user_id=%s', (entity_id, user_id))
        entity = cursor.fetchone()
        cursor.execute('SELECT id, amount, transaction_date, description FROM transactions WHERE receivable_id=%s ORDER BY transaction_date ASC', (entity_id,))
        txs = cursor.fetchall()
    conn.close()
    if not entity: return jsonify({'error': 'Not found'}), 404
    history_list = []
    running = entity['original_amount']
    for tx in txs:
        amt = tx['amount']
        running -= amt
        history_list.append({'id': tx['id'], 'amount': f"{abs(amt):.2f}", 'date': tx['transaction_date'],
                              'description': tx['description'] or '',
                              'tx_label': 'Payment' if amt > 0 else 'New Charge',
                              'tx_color': 'text-green-600' if amt > 0 else 'text-red-600',
                              'remaining_balance': f"{running:.2f}"})
    history_list.reverse()
    return jsonify({'name': entity['name'], 'original_amount': f"{entity['original_amount']:.2f}",
                    'remaining_amount': f"{entity['remaining_amount']:.2f}", 'history': history_list})

@app.route('/delete_transaction', methods=['POST'])
@login_required
def delete_transaction():
    user_id = session['user_id']
    data = request.get_json()
    tx_id = int(data.get('transaction_id'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM transactions WHERE id=%s AND user_id=%s', (tx_id, user_id))
        tx = cursor.fetchone()
        if not tx: return jsonify({'status': 'error', 'message': 'Not found.'}), 404
        amt = tx['amount']
        if tx['payable_id']:
            cursor.execute('UPDATE payables SET remaining_amount = remaining_amount + %s WHERE id=%s', (amt, tx['payable_id']))
        elif tx['receivable_id']:
            cursor.execute('UPDATE receivables SET remaining_amount = remaining_amount + %s WHERE id=%s', (amt, tx['receivable_id']))
        cursor.execute('DELETE FROM transactions WHERE id=%s', (tx_id,))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        expense_date = request.form.get('expense_date', '')
        amount = float(request.form.get('amount', 0))
        if not description or not expense_date or amount <= 0:
            flash('All fields are required.', 'danger')
            conn.close()
            return redirect(url_for('expenses'))
        cursor.execute('INSERT INTO expenses (user_id, description, expense_date, amount) VALUES (%s,%s,%s,%s)',
                     (user_id, description, expense_date, amount))
        conn.commit()
        flash('Expense recorded.', 'success')
        conn.close()
        return redirect(url_for('expenses'))
    cursor.execute('SELECT id, description, expense_date, amount FROM expenses WHERE user_id=%s ORDER BY expense_date DESC', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    expenses_list = [dict(r) for r in rows]
    total_expenses = sum(e['amount'] for e in expenses_list)
    return render_template('Expenses.html', expenses=expenses_list, total_expenses=total_expenses)

@app.route('/delete_expense', methods=['POST'])
@login_required
def delete_expense():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM expenses WHERE id=%s AND user_id=%s', (request.form.get('id'), user_id))
    conn.commit()
    conn.close()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))

@app.route('/daily_sales_summary')
@login_required
def daily_sales_summary():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, total_amount, sale_date, items_sold FROM sales WHERE user_id=%s ORDER BY sale_date DESC, id DESC', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    sales_list = []
    for r in rows:
        try:
            items = json.loads(r['items_sold'])
        except Exception:
            items = []
        sales_list.append({'id': r['id'], 'total_amount': r['total_amount'], 'sale_date': r['sale_date'], 'items': items})
    return render_template('daily_sales_summary.html', sales=sales_list)

@app.route('/setup-db')
def setup_db():
    init_db()
    return 'Database initialized successfully!'

@app.route('/setup-admin')
def setup_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
        cursor.execute("UPDATE users SET is_admin = TRUE WHERE username = 'admin'")
        cursor.execute("UPDATE users SET status = 'active' WHERE status IS NULL")
        conn.commit()
        return 'Admin setup complete! You can now log in as admin.'
    except Exception as e:
        conn.rollback()
        return f'Error: {str(e)}'
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)