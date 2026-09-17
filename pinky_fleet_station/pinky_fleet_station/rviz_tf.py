"""두 네임스페이스의 TF를 RViz 전용 토픽으로 모은다. 로봇 쪽 TF는 변경하지 않는다."""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from tf2_msgs.msg import TFMessage


class ViewTransforms(Node):
    def __init__(self):
        super().__init__('fleet_view_transforms')
        self.static = {}
        self.dynamic_pub = self.create_publisher(TFMessage, '/fleet_view/tf', 100)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.static_pub = self.create_publisher(TFMessage, '/fleet_view/tf_static', qos)
        for name in ('pinky1', 'pinky2'):
            self.create_subscription(TFMessage, f'/{name}/tf', self.dynamic_pub.publish, 100)
            self.create_subscription(TFMessage, f'/{name}/tf_static', self.on_static, qos)

    def on_static(self, msg):
        for transform in msg.transforms:
            self.static[transform.child_frame_id] = transform
        self.static_pub.publish(TFMessage(transforms=list(self.static.values())))


def main():
    rclpy.init()
    node = ViewTransforms()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
