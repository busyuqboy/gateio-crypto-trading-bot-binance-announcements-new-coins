import yaml


def load_binance_creds(file):
    with open(file) as file:
        auth = yaml.load(file, Loader=yaml.FullLoader)

    return auth['binance_api'], auth['binance_secret']
