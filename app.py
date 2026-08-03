from flask import Flask, render_template, request, redirect, Response
import sqlite3
import datetime
import csv
import io
import json

app = Flask(__name__)

def conectar_bd():
    return sqlite3.connect('estoque.db')

def criar_tabelas():
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            quantidade INTEGER NOT NULL,
            localizacao TEXT,
            minimo INTEGER DEFAULT 5
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER,
            quantidade INTEGER,
            retirado_por TEXT,
            data_hora TEXT,
            assinatura TEXT,
            FOREIGN KEY (produto_id) REFERENCES produtos (id)
        )
    ''')
    conn.commit()
    conn.close()

criar_tabelas()

@app.route('/')
def index():
    busca_historico = request.args.get('busca_historico', '').strip()
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    # 1. Busca lista de produtos
    cursor.execute('SELECT id, nome, quantidade, localizacao, minimo FROM produtos ORDER BY nome ASC')
    produtos = cursor.fetchall()
    
    # 2. Busca histórico (AGORA EM ORDEM CRESCENTE: h.id ASC)
    if busca_historico:
        cursor.execute('''
            SELECT h.id, p.nome, h.quantidade, h.retirado_por, h.data_hora, h.assinatura 
            FROM historico h
            JOIN produtos p ON h.produto_id = p.id
            WHERE p.nome LIKE ? OR h.retirado_por LIKE ? OR h.data_hora LIKE ?
            ORDER BY h.id ASC
        ''', (f'%{busca_historico}%', f'%{busca_historico}%', f'%{busca_historico}%'))
    else:
        cursor.execute('''
            SELECT h.id, p.nome, h.quantidade, h.retirado_por, h.data_hora, h.assinatura 
            FROM historico h
            JOIN produtos p ON h.produto_id = p.id
            ORDER BY h.id ASC
        ''')
    historico = cursor.fetchall()
    
    # 3. Dados para os Gráficos
    cursor.execute('''
        SELECT p.nome, SUM(h.quantidade) as total
        FROM historico h
        JOIN produtos p ON h.produto_id = p.id
        GROUP BY p.id
        ORDER BY total DESC
        LIMIT 5
    ''')
    top_retirados = cursor.fetchall()
    
    chart_top_labels = json.dumps([row[0] for row in top_retirados])
    chart_top_data = json.dumps([row[1] for row in top_retirados])
    
    chart_estoque_labels = json.dumps([p[1] for p in produtos])
    chart_estoque_qtd = json.dumps([p[2] for p in produtos])
    chart_estoque_min = json.dumps([p[4] for p in produtos])

    conn.close()
    
    return render_template(
        'index.html', 
        produtos=produtos, 
        historico=historico, 
        busca_historico=busca_historico,
        chart_top_labels=chart_top_labels,
        chart_top_data=chart_top_data,
        chart_estoque_labels=chart_estoque_labels,
        chart_estoque_qtd=chart_estoque_qtd,
        chart_estoque_min=chart_estoque_min
    )

@app.route('/cadastrar_produto', methods=['POST'])
def cadastrar_produto():
    nome = request.form['nome'].strip()
    quantidade = int(request.form['quantidade'])
    localizacao = request.form['localizacao'].strip()
    minimo = int(request.form.get('minimo', 5))
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, quantidade FROM produtos WHERE LOWER(nome) = LOWER(?)', (nome,))
    produto_existente = cursor.fetchone()
    
    if produto_existente:
        nova_qtd = produto_existente[1] + quantidade
        cursor.execute('''
            UPDATE produtos 
            SET quantidade = ?, localizacao = ?, minimo = ? 
            WHERE id = ?
        ''', (nova_qtd, localizacao, minimo, produto_existente[0]))
    else:
        cursor.execute('''
            INSERT INTO produtos (nome, quantidade, localizacao, minimo) 
            VALUES (?, ?, ?, ?)
        ''', (nome, quantidade, localizacao, minimo))
        
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/editar_produto/<int:id>', methods=['POST'])
def editar_produto(id):
    nome = request.form['nome'].strip()
    quantidade = int(request.form['quantidade'])
    localizacao = request.form['localizacao'].strip()
    minimo = int(request.form.get('minimo', 5))
    
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE produtos 
        SET nome = ?, quantidade = ?, localizacao = ?, minimo = ?
        WHERE id = ?
    ''', (nome, quantidade, localizacao, minimo, id))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/excluir_produto/<int:id>', methods=['POST'])
def excluir_produto(id):
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM produtos WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/')

# NOVA ROTA: Excluir registro individual do histórico
@app.route('/excluir_historico/<int:id>', methods=['POST'])
def excluir_historico(id):
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM historico WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/registrar_retirada', methods=['POST'])
def registrar_retirada():
    produto_id = request.form['produto_id']
    quantidade = int(request.form['quantidade'])
    retirado_por = request.form['retirado_por']
    assinatura = request.form['assinatura']
    
    data_hora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    cursor.execute('SELECT quantidade FROM produtos WHERE id = ?', (produto_id,))
    prod = cursor.fetchone()
    
    if prod and prod[0] >= quantidade:
        nova_qtd = prod[0] - quantidade
        cursor.execute('UPDATE produtos SET quantidade = ? WHERE id = ?', (nova_qtd, produto_id))
        cursor.execute('''
            INSERT INTO historico (produto_id, quantidade, retirado_por, data_hora, assinatura) 
            VALUES (?, ?, ?, ?, ?)
        ''', (produto_id, quantidade, retirado_por, data_hora, assinatura))
        conn.commit()
    
    conn.close()
    return redirect('/')

@app.route('/exportar_csv')
def exportar_csv():
    busca = request.args.get('busca', '').strip()
    
    conn = conectar_bd()
    cursor = conn.cursor()
    
    if busca:
        cursor.execute('''
            SELECT h.data_hora, p.nome, h.quantidade, h.retirado_por 
            FROM historico h
            JOIN produtos p ON h.produto_id = p.id
            WHERE p.nome LIKE ? OR h.retirado_por LIKE ? OR h.data_hora LIKE ?
            ORDER BY h.id ASC
        ''', (f'%{busca}%', f'%{busca}%', f'%{busca}%'))
    else:
        cursor.execute('''
            SELECT h.data_hora, p.nome, h.quantidade, h.retirado_por 
            FROM historico h
            JOIN produtos p ON h.produto_id = p.id
            ORDER BY h.id ASC
        ''')
        
    registros = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Data/Hora', 'Produto', 'Quantidade Retirada', 'Retirado por'])

    for reg in registros:
        writer.writerow(reg)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=historico_retiradas.csv"}
    )

@app.route('/exportar_estoque_csv')
def exportar_estoque_csv():
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute('SELECT nome, localizacao, quantidade, minimo FROM produtos ORDER BY nome ASC')
    produtos = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Produto', 'Localização', 'Qtd Atual', 'Qtd Mínima', 'Status'])

    for p in produtos:
        nome, loc, qtd, mini = p[0], p[1], p[2], p[3]
        if qtd == 0:
            status = 'ESGOTADO'
        elif qtd <= mini:
            status = 'ALERTA (BAIXO)'
        else:
            status = 'OK'
        writer.writerow([nome, loc, qtd, mini, status])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=relatorio_estoque_atual.csv"}
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)