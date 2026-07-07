from flask import Flask, render_template, jsonify, request
import json
import os

app = Flask(__name__)

# Percorsi relativi ai file generati dal controller Ryu
STATS_FILE = '../jsonFile/statistics.json'
AGG_STATS_FILE = '../jsonFile/aggregatedStats.json'
WHITELIST_FILE = '../jsonFile/whiteList.json'
BLACKLIST_FILE = '../jsonFile/blackList.json'
MITIGATION_LOG = '../log/Mitigation.txt'

@app.route('/')
def index():
    """Mostra la dashboard principale."""
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    """Restituisce le statistiche dei singoli flussi in tempo reale."""
    try:
        with open(STATS_FILE, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify([])

@app.route('/api/agg_stats')
def get_agg_stats():
    """Restituisce le statistiche aggregate (media, IQR, percentili, dev std)."""
    try:
        with open(AGG_STATS_FILE, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({})

@app.route('/api/policies')
def get_policies():
    """Restituisce il contenuto di whitelist e blacklist."""
    try:
        with open(WHITELIST_FILE, 'r') as fw, open(BLACKLIST_FILE, 'r') as fb:
            return jsonify({"whitelist": json.load(fw), "blacklist": json.load(fb)})
    except Exception:
        return jsonify({"whitelist": {}, "blacklist": {}})

@app.route('/api/alerts')
def get_alerts():
    """Restituisce le ultime 15 righe del log di mitigazione."""
    try:
        with open(MITIGATION_LOG, 'r') as f:
            lines = f.readlines()[-15:]
        return jsonify({"alerts": lines})
    except Exception:
        return jsonify({"alerts": ["File log/Mitigation.txt non ancora disponibile."]})

@app.route('/api/add_policy', methods=['POST'])
def add_policy():
    """Aggiunge una nuova regola alla whitelist o blacklist."""
    data = request.json
    list_type = data.get('list_type')
    
    # Costruisce la chiave del dizionario nel formato (in_port, 'mac_src', 'mac_dst')
    flow_key = f"({data.get('in_port')}, '{data.get('eth_src')}', '{data.get('eth_dst')}')"
    reason = data.get('reason', 'Aggiunto manualmente via Web UI')

    file_path = WHITELIST_FILE if list_type == 'whitelist' else BLACKLIST_FILE

    try:
        current_list = {}
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if content:
                    current_list = json.loads(content)

        current_list[flow_key] = {
            "enabled": True,
            "reason": reason
        }

        with open(file_path, 'w') as f:
            json.dump(current_list, f, indent=2)

        return jsonify({"status": "success", "message": f"Regola aggiunta alla {list_type} con successo!"})
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete_policy', methods=['POST'])
def delete_policy():
    """Elimina una regola esistente dalla whitelist o blacklist."""
    data = request.json
    list_type = data.get('list_type')
    flow_key = data.get('flow_key')

    file_path = WHITELIST_FILE if list_type == 'whitelist' else BLACKLIST_FILE

    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                current_list = json.load(f)
            
            # Se la chiave esiste, la elimina dal dizionario
            if flow_key in current_list:
                del current_list[flow_key]
                
                with open(file_path, 'w') as f:
                    json.dump(current_list, f, indent=2)
                    
                return jsonify({"status": "success", "message": "Regola rimossa con successo."})
                
        return jsonify({"status": "error", "message": "Regola non trovata."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Avvia il server Flask sulla porta 5000
    app.run(host='0.0.0.0', port=5000, debug=True)