# /config/custom_components/eyzee_dashboard/minimal_binding.py
# SIMPLE BINDING CREATION

async def handle_create_binding(hass, call):
    """Create a simple toggle binding between switch and light."""
    
    switch_entity = call.data.get("switch")
    light_entity = call.data.get("light")
    
    if not switch_entity or not light_entity:
        hass.components.persistent_notification.async_create(
            "Please select both a switch and a light",
            title="EyZEE Binding Error"
        )
        return False
    
    # Create simple automation
    automation_id = f"eyzee_binding_{switch_entity.replace('.', '_')}_to_{light_entity.replace('.', '_')}"
    
    automation_config = {
        "id": automation_id,
        "alias": f"{switch_entity} controls {light_entity}",
        "description": "Created by EyZEE Device Wizard",
        "trigger": {
            "platform": "state",
            "entity_id": switch_entity,
            "to": "on"
        },
        "action": {
            "service": "light.toggle",
            "target": {"entity_id": light_entity}
        }
    }
    
    # Save to automations.yaml
    automations_path = hass.config.path("automations.yaml")
    
    try:
        with open(automations_path, 'r') as f:
            existing = yaml.safe_load(f) or []
    except FileNotFoundError:
        existing = []
    
    # Add new automation
    existing.append(automation_config)
    
    with open(automations_path, 'w') as f:
        yaml.dump(existing, f, default_flow_style=False)
    
    hass.components.persistent_notification.async_create(
        f"✅ Created binding:\n{switch_entity} → {light_entity}",
        title="EyZEE Binding Created"
    )
    
    # Reload automations
    await hass.services.async_call("automation", "reload", {})
    
    return True
    