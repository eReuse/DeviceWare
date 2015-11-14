import copy

from app.device.component.settings import component, component_sub_settings

motherboard_settings = copy.deepcopy(component_sub_settings)

motherboard_settings.update({
    'schema': copy.deepcopy(component),
    'url': component_sub_settings['url'] + 'motherboard'
})