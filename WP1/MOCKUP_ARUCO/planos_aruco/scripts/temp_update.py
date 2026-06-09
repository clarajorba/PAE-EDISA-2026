import json

# Cargar el archivo
with open(r"c:\Users\clara\Desktop\UPC\10è quatrimestre\PAE\MOCKUP_ARUCO\planos_aruco\scripts\flight_sequence.json", 'r') as f:
    data = json.load(f)

# Actualizar descripciones
for item in data:
    item['description'] = item['description'].replace('enviar posición GPS', 'enviar coordenadas locales')

# Guardar
with open(r"c:\Users\clara\Desktop\UPC\10è quatrimestre\PAE\MOCKUP_ARUCO\planos_aruco\scripts\flight_sequence.json", 'w') as f:
    json.dump(data, f, indent=2)

print("Archivo actualizado")