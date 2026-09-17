"""상위 패키지를 수정하지 않고 네임스페이스 URDF의 Gazebo 참조를 보정한다."""
from pathlib import Path
import xml.etree.ElementTree as ET
import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    name = LaunchConfiguration('namespace').perform(context)
    prefix = name + '/'
    description = Path(get_package_share_directory('pinky_description')) / 'urdf/robot.urdf.xacro'
    document = xacro.process_file(str(description), mappings={'namespace':prefix, 'is_sim':'true', 'cam_tilt_deg':'0'})
    root = ET.fromstring(document.toxml())
    links = {element.get('name') for element in root.findall('link')}
    # URDF 링크는 base_link처럼 접두사가 없는데 Gazebo reference는 pinky1/base_link다.
    # 존재하지 않는 참조의 접두사만 제거하고 토픽·TF frame 이름은 그대로 둔다.
    for gazebo in root.findall('gazebo'):
        ref = gazebo.get('reference', '')
        if ref.startswith(prefix) and ref[len(prefix):] in links:
            gazebo.set('reference', ref[len(prefix):])
    for link in root.findall('.//plugin/link'):
        if link.text and link.text.startswith(prefix) and link.text[len(prefix):] in links:
            link.text = link.text[len(prefix):]
    xml = ET.tostring(root, encoding='unicode')
    config = Path(get_package_share_directory('pinky_fleet_sim')) / f'params/{name}_bridge.yaml'
    return [
        Node(package='robot_state_publisher', executable='robot_state_publisher', namespace=name,
             parameters=[{'robot_description':xml, 'frame_prefix':prefix, 'use_sim_time':True}],
             remappings=[('/tf','tf'),('/tf_static','tf_static')]),
        Node(package='ros_gz_sim', executable='create', name='spawn_'+name,
             arguments=['-name',name,'-topic',f'/{name}/robot_description',
                        '-x',LaunchConfiguration('x'),'-y',LaunchConfiguration('y'),'-z','0.05','-Y',LaunchConfiguration('yaw')]),
        Node(package='ros_gz_bridge', executable='parameter_bridge', name='bridge_'+name,
             parameters=[{'config_file':str(config), 'use_sim_time':True}])]


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument(key, default_value=value) for key,value in
                              [('namespace','pinky1'),('x','0.0'),('y','0.0'),('yaw','0.0')]] + [OpaqueFunction(function=setup)])
