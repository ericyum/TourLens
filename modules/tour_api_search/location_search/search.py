import gradio as gr
from utils import session, common_params, BASE_URL, get_api_items

def find_nearby_places(latitude, longitude):
    if not latitude or not longitude: return gr.update(choices=[], value=None), {}
    try:
        params = {**common_params, "mapX": str(longitude), "mapY": str(latitude), "radius": "5000", "numOfRows": "20"}
        response = session.get(f"{BASE_URL}locationBasedList2", params=params)
        response.raise_for_status()
        
        items = get_api_items(response.json())
        
        if not items: return gr.update(choices=[], value=None), {}
        
        places_info = {
            item['title']: (item['contentid'], item['contenttypeid']) 
            for item in items 
            if isinstance(item, dict) and 'title' in item
        }
        
        return gr.update(choices=list(places_info.keys()), value=None), places_info
    except Exception as e:
        print(f"[find_nearby_places error] {e}")
        return gr.update(choices=[], value=None), {}