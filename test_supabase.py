import streamlit as st
from supabase import Client, create_client

url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
key = str(st.secrets["SUPABASE_SERVICE_KEY"]).strip()

print("URL:", url)
print("密钥类型:", key[:10])
print("密钥长度:", len(key))

client: Client = create_client(url, key)

result = (
    client.table("app_users")
    .select("username")
    .limit(1)
    .execute()
)

print("连接成功:", result.data)