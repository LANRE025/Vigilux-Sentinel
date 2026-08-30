from google import genai

client = genai.Client(
    vertexai=True,
    project="vigilux-sentinel",
    location="global",
)
response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Say hello in one word."
)
print(response.text)