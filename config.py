APIS = [
    {
        "SCADDRESS": "erd1qqqqqqqqqqqqqpgqsrpfn4rzp0me4qrhpguznvsjrugmzez0u7zs2a0cu0",
        "ABI_PATH": "gxy.abi.json",
        "NAME": "GXY"
    }
]
PORT = 8080
ENVIRONMENT = "devnet"
ENVIRONMENTS = {
    "mainnet": "https://gateway.multiversx.com",
    "devnet": "https://devnet-gateway.multiversx.com",
    "testnet": "https://testnet-gateway.multiversx.com"
}
PROXY_URL = ENVIRONMENTS[ENVIRONMENT]
SIZE_PER_TYPE = {
    "i8": 1,
    "i16": 2,
    "i32": 4,
    "i64": 8,
    "i128": 16,
    "u8": 1,
    "u16": 2,
    "u32": 4,
    "u64": 8,
    "u128": 16,
}
