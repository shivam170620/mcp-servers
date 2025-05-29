# MCP Server 

{
     "mcpServer":{
        "weather": {
        "command": "/opt/anaconda3/bin/uv",
        "args": [
          "--directory",
          "/Users/shivamkumar/Documents/GEN AI/MCP_Servers/mcp-servers/weather",
          "run",
          "weather.py"
        ], "env": {
          "ACCUWEATHER_API_KEY": "api_key"
        }
      }
     }
}