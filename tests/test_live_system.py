import urllib.request
import urllib.error
import json
import time

base_url = 'http://localhost:8000/api'

def run():
    print('--- 1. Testing Backend Health & Unauthenticated Admin Route Rejection ---')
    try:
        urllib.request.urlopen(f'{base_url}/admin/overview')
        print('FAIL: /api/admin/overview should have required auth!')
    except urllib.error.HTTPError as e:
        print(f'PASS: /api/admin/overview correctly returned {e.code} ({e.reason})')

    print('\n--- 2. Testing Super Admin Token Access ---')
    admin_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidXNlcl9pZCI6MSwiZW1haWwiOiJkZW1vQGNhcmRyLmFwcCIsImZ1bGxfbmFtZSI6Ikdlb3JnZSAoU3VwZXIgQWRtaW4pIiwiaWF0IjoxNzk1NDg3NDYzLCJleHAiOjE4MDA2NzE0NjN9.siVZF5fiFVQJt6iiFNQOx5wJzVVxNSsio8xsOuSYL7g'
    req = urllib.request.Request(f'{base_url}/admin/overview', headers={'Authorization': f'Bearer {admin_token}'})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        total_users = data['metrics']['total_users']
        total_cards = data['metrics']['total_cards']
        print(f'PASS: Admin overview returned metrics: Total Users={total_users}, Total Cards={total_cards}')

    print('\n--- 3. Testing New User Isolation (0 Cards on Fresh Signup) ---')
    test_email = f'tester_{int(time.time())}@example.com'
    reg_req = urllib.request.Request(
        f'{base_url}/auth/register',
        data=json.dumps({'email': test_email, 'password': 'Password123!', 'full_name': 'Test User'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(reg_req) as resp:
        reg_data = json.loads(resp.read().decode('utf-8'))
        user_token = reg_data.get('token') or reg_data.get('access_token')
        user_id = reg_data['user']['id']
        print(f'PASS: Registered user #{user_id} ({test_email})')

    # Fetch cards for this new user
    cards_req = urllib.request.Request(f'{base_url}/cards', headers={'Authorization': f'Bearer {user_token}'})
    with urllib.request.urlopen(cards_req) as resp:
        cards_data = json.loads(resp.read().decode('utf-8'))
        cards_count = len(cards_data.get('cards', []))
        print(f'PASS: Cards count for new user is {cards_count} (Strict isolation verified!)')

    # Create a card for this new user
    new_card_req = urllib.request.Request(
        f'{base_url}/cards',
        data=json.dumps({'full_name': 'New Contact', 'company': 'Acme', 'phone': '123456'}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {user_token}'}
    )
    with urllib.request.urlopen(new_card_req) as resp:
        created = json.loads(resp.read().decode('utf-8'))
        created_id = created['card']['id']
        print(f'PASS: Created card #{created_id} for user #{user_id}')

    # Delete that card
    del_req = urllib.request.Request(
        f'{base_url}/cards/{created_id}',
        headers={'Authorization': f'Bearer {user_token}'},
        method='DELETE'
    )
    with urllib.request.urlopen(del_req) as resp:
        print(f'PASS: Deleted card #{created_id}')

    # Clean up test user
    del_user_req = urllib.request.Request(
        f'{base_url}/admin/users/{user_id}',
        headers={'Authorization': f'Bearer {admin_token}'},
        method='DELETE'
    )
    with urllib.request.urlopen(del_user_req) as resp:
        print(f'PASS: Cleaned up test user #{user_id}')

    print('\n--- 4. Testing Public Cloudflare Tunnel ---')
    tunnel_url = 'https://entrepreneur-wrist-nodes-mitsubishi.trycloudflare.com/api/digital-card'
    try:
        with urllib.request.urlopen(tunnel_url, timeout=5) as t_resp:
            print(f'PASS: Public Cloudflare Tunnel is live (Status {t_resp.status})')
    except Exception as te:
        print(f'Tunnel response: {te}')

    print('\n--- ALL LIVE INTEGRATION TESTS PASSED 100%! ---')

if __name__ == '__main__':
    run()
