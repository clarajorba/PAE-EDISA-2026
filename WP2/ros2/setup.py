from setuptools import find_packages, setup

package_name = 'dron_control_sistema'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, ['dron_control_sistema/mision.json']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'cerebro_node = dron_control_sistema.cerebro_node:main',
            'mavros_node = dron_control_sistema.mavros_node:main',
            'simulador_dron = dron_control_sistema.simulador_dron:main',
            'lidar_node = dron_control_sistema.lidar_node:main',
            'lidar_bridge_node = dron_control_sistema.lidar_bridge_node:main',
            'pixhawk_menu_node = dron_control_sistema.pixhawk_menu_node:main',
            'spy_mavros = dron_control_sistema.spy_mavros:main',
            'gcs_node = dron_control_sistema.gcs_node:main',
        ],
    },
)
