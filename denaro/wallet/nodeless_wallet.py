import argparse
import asyncio
import os
import sys
from decimal import Decimal

import pickledb
import requests
from fastecdsa import keys, curve

from denaro.wallet.utils import string_to_bytes

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, dir_path + "/../..")

from denaro.transactions import Transaction, TransactionOutput, TransactionInput
from denaro.constants import CURVE
from denaro.helpers import point_to_string, sha256, string_to_point

NODE_URL = 'https://denaro-node.gaetano.eu.org'


def get_address_info(address: str):
    request = requests.get(f'{NODE_URL}/get_address_info', {'address': address})
    result = request.json()['result']
    tx_inputs = []
    for spendable_tx_input in result['spendable_outputs']:
        tx_input = TransactionInput(spendable_tx_input['tx_hash'], spendable_tx_input['index'])
        tx_input.amount = Decimal(str(spendable_tx_input['amount']))
        tx_input.public_key = string_to_point(address)
        tx_inputs.append(tx_input)
    return result['balance'], tx_inputs


def create_transaction(private_keys, receiving_address, amount, message: bytes = None):
    amount = Decimal(amount)
    inputs = []
    for private_key in private_keys:
        address = point_to_string(keys.get_public_key(private_key, curve.P256))
        _, address_inputs = get_address_info(address)
        for address_input in address_inputs:
            address_input.private_key = private_key
        inputs.extend(address_inputs)

        if sum(input.amount for input in inputs) >= amount:
            break
    if not inputs:
        raise Exception('No spendable outputs')

    if sum(input.amount for input in inputs) < amount:
        raise Exception(f"Error: You don\'t have enough funds")

    most_amount = sorted(inputs, key=lambda item: item.amount, reverse=True)

    transaction_inputs = []

    for i, tx_input in enumerate(most_amount):
        transaction_inputs.append(tx_input)
        transaction_amount = sum(input.amount for input in transaction_inputs)
        if transaction_amount >= amount:
            break

    transaction_amount = sum(input.amount for input in transaction_inputs)

    transaction = Transaction(transaction_inputs, [TransactionOutput(receiving_address, amount=amount)], message)
    if transaction_amount > amount:
        transaction.outputs.append(TransactionOutput(address, transaction_amount - amount))

    transaction.sign(private_keys)

    requests.get(f'{NODE_URL}/push_tx', {'tx_hex': transaction.hex()}, timeout=10)
    return transaction


async def main():
    parser = argparse.ArgumentParser(description='Denaro wallet')
    parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet', choices=['createwallet', 'send', 'balance'])
    parser.add_argument('-to', metavar='recipient', type=str, required=False)
    parser.add_argument('-d', metavar='amount', type=str, required=False)
    parser.add_argument('-m', metavar='message', type=str, dest='message', required=False)

    args = parser.parse_args()
    db = pickledb.load(f'{dir_path}/wallet.json', True)

    command = args.command

    if command == 'createwallet':
        private_keys = db.get('private_keys') or []
        private_key = keys.gen_private_key(CURVE)
        private_keys.append(private_key)
        db.set('private_keys', private_keys)

        public_key = keys.get_public_key(private_key, curve.P256)
        address = point_to_string(public_key)

        print(f'Private key: {hex(private_key)}\nAddress: {address}')
    elif command == 'balance':
        private_keys = db.get('private_keys') or []
        total_balance = 0
        for private_key in private_keys:
            public_key = keys.get_public_key(private_key, curve.P256)
            address = point_to_string(public_key)
            balance, _ = get_address_info(address)
            total_balance += balance
            pending_balance = balance  # fixme
            print(f'\nAddress: {address}\nPrivate key: {hex(private_key)}\nBalance: {balance}{f" ({pending_balance - balance} pending)" if pending_balance - balance != 0 else ""}')
        print(f'\nTotal Balance: {total_balance}')
    elif command == 'send':
        parser = argparse.ArgumentParser()
        parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet')
        parser.add_argument('-to', metavar='recipient', type=str, dest='recipient', required=True)
        parser.add_argument('-d', metavar='amount', type=str, dest='amount', required=True)
        parser.add_argument('-m', metavar='message', type=str, dest='message', required=False)

        args = parser.parse_args()
        receiver = args.recipient
        amount = args.amount
        message = args.message

        tx = create_transaction(db.get('private_keys'), receiver, amount, string_to_bytes(message))
        print(f'Transaction pushed. Transaction hash: {sha256(tx.hex())}')


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
