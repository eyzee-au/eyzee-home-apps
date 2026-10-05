# /config/custom_components/eyzee_dashboard/simple_discovery.py
# MINIMAL DISCOVERY FOR WORKING DEVICES

import yaml

async def discover_existing_devices(hass):
    """Find existing EyZEE devices that are already working."""
    
    discovered = []
    
    # Scan all switch entities
    switch_entities = hass.states.async_entity_ids("switch")
    
    for entity_id in switch_entities:
        state = hass.states.get(entity_id)
        friendly_name = state.attributes.get("friendly_name", "")
        
        # Check if it looks like an EyZEE device
        if "eyzee" in friendly_name.lower() or "eyzee" in entity_id.lower():
            
            # Try to determine type
            if "_l1" in entity_id or "_l2" in entity_id or "_l3" in entity_id or "_l4" in entity_id:
                device_type = "eyzee_4ch_relay_switch"
            elif "2gang" in friendly_name.lower() or "two" in friendly_name.lower():
                device_type = "eyzee_2gang_switch"
            else:
                device_type = "eyzee_switch"
            
            discovered.append({
                "entity_id": entity_id,
                "friendly_name": friendly_name,
                "device_type": device_type,
                "state": state.state,
                "discovered_at": datetime.now().isoformat()
            })
    
    return discovered

async def handle_discover_devices(call):
    """Service to discover existing EyZEE devices."""
    
    discovered = await discover_existing_devices(hass)
    
    if not discovered:
        hass.components.persistent_notification.async_create(
            "No EyZEE devices found. Make sure they're already paired in Zigbee2MQTT.",
            title="EyZEE Discovery"
        )
        return
    
    # Save discovery results
    discovery_path = hass.config.path("eyzee/devices/discovered_devices.yaml")
    
    with open(discovery_path, 'w') as f:
        yaml.dump(discovered, f, default_flow_style=False)
    
    # Create summary notification
    summary = f"Found {len(discovered)} EyZEE devices:\n"
    for device in discovered:
        summary += f"- {device['entity_id']} ({device['device_type']})\n"
    
    hass.components.persistent_notification.async_create(
        summary,
        title="EyZEE Devices Found!"
    )
    
    return True
    